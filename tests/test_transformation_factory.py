import os
import re
import subprocess
import sys

import pytest

from pyfedappwrap.learning.base_app import BaseApp
from pyfedappwrap.transformation.config.transformer_config import BaseTransformerConfig
from pyfedappwrap.transformation.validate.datatype_dto import DataTypeTransformationGoalDTO, DataTypes, \
    DataTypeValidationDTO, DataTypeValidationType
from pyfedappwrap.transformation.factory.factory_builder import TransformationBuilder
from pyfedappwrap.transformation.factory.factory_test import TransformationTester, \
    test_function as run_factory_test
from pyfedappwrap.transformation.factory.factory_test_result import TransformationTestCaseDTO
from pyfedappwrap.transformation.transformation_mode import FunctionExecutionMode

HEADER = """
from pyfedappwrap.transformation.base_transformer import BaseTransformerAPP
from pyfedappwrap.transformation.config.transformer_config import BaseTransformerConfig
"""

ROW_SUM = HEADER + """
class Sum(BaseTransformerAPP[BaseTransformerConfig]):
    def transform(self, data):
        return data["a"] + data["b"]
"""


def _dt(type_: DataTypes, **validations) -> DataTypeTransformationGoalDTO:
    return DataTypeTransformationGoalDTO(type=type_, validations=[
        DataTypeValidationDTO(name=DataTypeValidationType(k.upper()), validator=str(v), message="")
        for k, v in validations.items()
    ])


def test_build_requires_exactly_one_transformer() -> None:
    assert TransformationBuilder(ROW_SUM).build().transform({"a": 1, "b": 2}) == 3
    with pytest.raises(ValueError, match="found: none"):
        TransformationBuilder(HEADER)
    with pytest.raises(ValueError, match="found: Sum, Other"):
        TransformationBuilder(ROW_SUM + ROW_SUM.replace("class Sum", "class Other").replace(HEADER, ""))


@pytest.mark.parametrize("source,error", [
    ("", "must not be empty"),
    ("  \n", "must not be empty"),
    ("class (", "does not compile, line 1"),
    ("import not_a_module_xyz", "'not_a_module_xyz' is not installed"),
    ("raise RuntimeError('x')", "Executing the source code failed, RuntimeError"),
    (HEADER + "class Missing(BaseTransformerAPP[BaseTransformerConfig]):\n    pass\n", "found: none"),
])
def test_invalid_source_is_rejected(source, error) -> None:
    with pytest.raises(ValueError, match=error):
        TransformationBuilder(source)


def _transformer(signature: str, body: str = "return None") -> str:
    return HEADER + f"""
from typing import Any, Optional, Union

class T(BaseTransformerAPP[BaseTransformerConfig]):
    {signature}:
        {body}
"""


ROW, CELL, PATIENT = FunctionExecutionMode.ROW, FunctionExecutionMode.CELL, FunctionExecutionMode.PATIENT


@pytest.mark.parametrize("signature,mode", [
    ("def transform(self, data)", ROW),
    ("def transform(self, data: dict)", ROW),
    ("def transform(self, data: dict[str, Any])", ROW),
    ("def transform(self, value: str)", CELL),
    ("def transform(self, value: Optional[float])", CELL),
    ("def transform(self, rows: list[dict])", PATIENT),
    ("def transform(self, data: Union[list[dict[str, Any]], dict[str, str], str])", ROW),
    ("def transform(self, data: Union[list[dict[str, Any]], dict[str, str], str])", CELL),
    ("def transform(self, data: Union[list[dict[str, Any]], dict[str, str], str])", PATIENT),
    ("def transform(self, value: str, unit: str = 'mg')", CELL),
    ("def transform(self, *values)", CELL),
    ("def transform(self, value: str)", None),
])
def test_transform_fitting_the_mode_is_accepted(signature, mode) -> None:
    TransformationBuilder(_transformer(signature), mode)


@pytest.mark.parametrize("signature,mode,error", [
    ("def transform(self, value: str)", ROW, "takes value: str, but a ROW transformation passes a dict"),
    ("def transform(self, data: dict)", CELL, "CELL transformation passes a single value"),
    ("def transform(self, data: dict)", PATIENT, "PATIENT transformation passes a list of row dicts"),
    ("def transform(self, value: Optional[str])", ROW, "ROW transformation passes a dict"),
    ("def transform(self)", None, "must take exactly one argument"),
    ("def transform(self, a, b)", None, "must take exactly one argument"),
    ("def transform(self, a, *, b)", None, "must take exactly one argument"),
    ("async def transform(self, value)", None, "not be async or a generator"),
])
def test_transform_not_fitting_is_rejected(signature, mode, error) -> None:
    with pytest.raises(ValueError, match=re.escape(error)):
        TransformationBuilder(_transformer(signature), mode)


def test_generator_transform_is_rejected() -> None:
    with pytest.raises(ValueError, match="not be async or a generator"):
        TransformationBuilder(_transformer("def transform(self, value)", "yield value"))


def test_function_reports_mode_mismatch() -> None:
    result = run_factory_test(DataTypeTransformationGoalDTO(type=DataTypes.STRING),
                              _transformer("def transform(self, value: str)", "return value"),
                              data={"v": ["a"]}, mode=ROW)
    assert not result.is_success
    assert "ROW transformation passes a dict" in result.message


def test_save_writes_source_as_module(tmp_path) -> None:
    builder = TransformationBuilder(ROW_SUM.replace("class Sum", "class BMIToHTTPCode"))
    path = builder.save(tmp_path / "transformers")
    assert path == tmp_path / "transformers" / "bmi_to_http_code.py"
    assert path.read_text(encoding="utf-8") == builder.source_code

    with pytest.raises(FileExistsError):
        builder.save(tmp_path / "transformers")
    assert builder.save(tmp_path / "transformers", overwrite=True) == path
    assert [p.name for p in (tmp_path / "transformers").iterdir()] == ["bmi_to_http_code.py"]


def test_wrapped_body_resolves_the_transformer_config() -> None:
    builder = TransformationBuilder(TransformationBuilder.wrap_body("return value", FunctionExecutionMode.CELL))
    assert BaseApp._resolve_baseapp_types(builder.transformer_class)[0] is BaseTransformerConfig


@pytest.mark.parametrize("maximum,code", [(10, 0), (2, 1)])
def test_registered_main_tests_against_the_case(tmp_path, maximum, code) -> None:
    builder = TransformationBuilder(ROW_SUM)
    case = TransformationTestCaseDTO(mode=FunctionExecutionMode.ROW, goal=_dt(DataTypes.INT, max=maximum),
                                     data={"a": [1, 2], "b": [3, 4]})
    main = builder.register(builder.save(tmp_path), case)
    assert main.read_text(encoding="utf-8").splitlines()[1] == "from sum import Sum"
    assert TransformationTestCaseDTO.model_validate_json((tmp_path / "test.json").read_text()) == case
    result = subprocess.run([sys.executable, "-m", "main"], cwd=tmp_path, capture_output=True, text=True,
                            env={**os.environ, "TEST_MODE": "true"}, check=False)
    assert result.returncode == code, result.stderr


def test_row_with_generated_data() -> None:
    sources = {"a": _dt(DataTypes.INT, min=0, max=5), "b": _dt(DataTypes.INT, min=0, max=5)}
    result = run_factory_test(_dt(DataTypes.INT, min=0, max=10), ROW_SUM, sourceGoals=sources)
    assert result.is_success, result.message

    result = run_factory_test(_dt(DataTypes.INT, max=3), ROW_SUM, data={"a": [1, 2], "b": [1, 4]})
    assert not result.is_success
    assert "1 of 2 results" in result.message


def test_cell_and_patient_modes() -> None:
    upper = HEADER + """
class Upper(BaseTransformerAPP[BaseTransformerConfig]):
    def transform(self, value):
        return value.upper()
"""
    goal = _dt(DataTypes.STRING, pattern="[A-Z]+")
    sources = {"v": _dt(DataTypes.STRING, minlength=2, maxlength=4)}
    assert run_factory_test(goal, upper, sourceGoals=sources, mode=FunctionExecutionMode.CELL).is_success

    count = HEADER + """
class Count(BaseTransformerAPP[BaseTransformerConfig]):
    def transform(self, rows):
        return [{"n": len(rows)}], [0]
"""
    result = run_factory_test(_dt(DataTypes.INT, min=3), count, data={"v": [1, 2, 3]},
                              mode=FunctionExecutionMode.PATIENT)
    assert result.is_success, result.message


@pytest.mark.parametrize("goal,source,data,error", [
    (_dt(DataTypes.INT, min=5, max=1), ROW_SUM, {"a": [1], "b": [1]}, "Invalid goal"),
    (_dt(DataTypes.INT), "class (", {"a": [1], "b": [1]}, "Building the transformation failed, Source code does not compile"),
    (_dt(DataTypes.INT), ROW_SUM, {"a": [1]}, "Transformation failed, KeyError"),
    (_dt(DataTypes.INT), ROW_SUM, {"a": [1], "b": [1, 2]}, "same length"),
    (_dt(DataTypes.INT), ROW_SUM, None, "No data provided"),
])
def test_failures_are_reported(goal, source, data, error) -> None:
    result = run_factory_test(goal, source, data=data)
    assert not result.is_success
    assert error in result.message


def test_tester_rejects_invalid_goals() -> None:
    with pytest.raises(ValueError, match="MIN 5 is greater than MAX 1"):
        TransformationTester(_dt(DataTypes.INT, min=5, max=1))
    with pytest.raises(ValueError, match="source 'a'"):
        TransformationTester(_dt(DataTypes.INT), {"a": _dt(DataTypes.STRING, min=1)})


def test_tester_checks_several_sources_against_one_goal() -> None:
    tester = TransformationTester(_dt(DataTypes.INT, min=0, max=10),
                                  {"a": _dt(DataTypes.INT, min=0, max=5), "b": _dt(DataTypes.INT, min=0, max=5)})
    assert tester.test(ROW_SUM).is_success
    assert not tester.test(ROW_SUM.replace('data["a"] + data["b"]', 'data["a"] + data["b"] + 100')).is_success
    assert tester.test(ROW_SUM, data={"a": 1, "b": 2}).is_success


@pytest.mark.parametrize("body,error", [
    ("import os\nreturn value", "Line 4: importing 'os' is not allowed"),
    ("from subprocess import run\nreturn value", "importing 'subprocess' is not allowed"),
    ("from . import x\nreturn value", "importing '' is not allowed"),
    ("return open(value)", "Line 4: using 'open' is not allowed"),
    ("return value.__class__", "using '__class__' is not allowed"),
    ("return (", "Source code does not compile, line 4"),
])
def test_static_check_rejects_unsafe_body(body, error) -> None:
    with pytest.raises(ValueError, match=re.escape(error)):
        TransformationBuilder(TransformationBuilder.wrap_body(body, CELL), CELL)


def test_wrapped_body_reports_keys() -> None:
    body = 'import math\nreturn {"bmi": math.floor(row["weight"] / row["height"] ** 2)}'
    builder = TransformationBuilder(TransformationBuilder.wrap_body(body, ROW), ROW)
    assert (builder.input_keys, builder.return_keys) == (["weight", "height"], ["bmi"])
    assert builder.build().transform({"weight": 80, "height": 2}) == {"bmi": 20}
    result = TransformationTester(_dt(DataTypes.INT), mode=ROW).test(builder.source_code, {"weight": [80], "height": [2]})
    assert result.model_dump(by_alias=True) == {"isSuccess": True, "message": result.message,
                                                "inputKeys": ["weight", "height"], "returnKeys": ["bmi"],
                                                "samples": [{"input": {"weight": 80, "height": 2}, "output": {"bmi": 20},
                                                             "error": None}]}


def test_cell_checks_every_column_and_rules_without_message() -> None:
    goal = DataTypeTransformationGoalDTO(type=DataTypes.INT, validations=[{"name": "MAX", "validator": "10"}])
    upper = TransformationBuilder.wrap_body("return int(value) * 2", CELL)
    assert TransformationTester(goal, mode=CELL).test(upper, {"a": ["1", "2"], "b": ["3", "4"]}).is_success
    result = TransformationTester(goal, mode=CELL).test(upper, {"a": ["1"], "b": ["6"]})
    assert result.message == "1 of 2 results do not match the goal"
    assert [s.model_dump() for s in result.samples] == [{"input": "6", "output": 12, "error": "Must be at most 10"},
                                                       {"input": "1", "output": 2, "error": None}]

from typing import Optional, Any

import pandas as pd

from pyfedappwrap.generator import DataTypeRandomGenerator
from pyfedappwrap.transformation.base_transformer import BaseTransformerAPP
from pyfedappwrap.transformation.validate.datatype_dto import DataTypeTransformationGoalDTO, DataTypes
from pyfedappwrap.transformation.factory.factory_builder import TransformationBuilder
from pyfedappwrap.transformation.factory.factory_test_result import \
    TransformationFactoryTestResultDTO
from pyfedappwrap.transformation.transformation_mode import FunctionExecutionMode
from pyfedappwrap.transformation.validate.validate import normalize_value, validate, validate_value

MAX_REPORTED_ERRORS = 5


class TransformationTester:
    """
    Tests transformations against a goal data type.

    The input is the given data ({column: [values]} or a single row {column: value}) or, if
    none is given, ``amount`` random rows generated from ``source_goals``. The columns are the
    parameters of the transformation. How ``transform`` is called depends on ``mode``:
      - ROW: once per row with a dict {parameter: value};
      - CELL: once per value of the single column;
      - PATIENT: once with all rows, as if they belonged to one patient.
    A result may be a value or a dict holding exactly one value.

    Raises:
        ValueError: If the goal or one of the source goals is invalid.
    """

    def __init__(self, goal: DataTypeTransformationGoalDTO,
                 source_goals: Optional[dict[str, DataTypeTransformationGoalDTO]] = None,
                 mode: FunctionExecutionMode = FunctionExecutionMode.ROW,
                 amount: int = 10):
        validate(goal)
        for name, source_goal in (source_goals or {}).items():
            try:
                validate(source_goal)
            except ValueError as e:
                raise ValueError(f"source '{name}': {e}") from e
        self.goal = goal
        self.source_goals = source_goals
        self.mode = mode
        self.amount = amount

    def test(self, source_code: str,
             data: Optional[dict[str, object]] = None) -> TransformationFactoryTestResultDTO:
        # pylint: disable=broad-exception-caught
        if data is None:
            data = self._generate_data()
        if not data:
            return self._fail("No data provided for testing")

        try:
            rows = self._to_rows(data)
        except ValueError as e:
            return self._fail(str(e))

        try:
            transformer = TransformationBuilder(source_code, self.mode).build()
        except ValueError as e:
            return self._fail(f"Building the transformation failed, {e}")

        try:
            results = self._run(transformer, rows)
        except Exception as e:
            return self._fail(f"Transformation failed, {type(e).__name__}: {e}")

        errors = self._check_results(results)
        if errors:
            shown = "; ".join(errors[:MAX_REPORTED_ERRORS])
            more = f" (and {len(errors) - MAX_REPORTED_ERRORS} more)" if len(errors) > MAX_REPORTED_ERRORS else ""
            return self._fail(f"{len(errors)} of {len(results)} results do not match the goal: {shown}{more}")

        return TransformationFactoryTestResultDTO(
            is_success=True, message=f"Test successful, {len(results)} results match the goal")

    def _generate_data(self) -> Optional[dict[str, object]]:
        if self.source_goals is None:
            return None
        generated = DataTypeRandomGenerator().generate_data(self.source_goals, self.amount)
        return {col: [self._typed(v, self.source_goals[col]) for v in values]
                for col, values in generated.items()}

    def _run(self, transformer: BaseTransformerAPP, rows: list[dict[str, Any]]) -> list[Any]:
        if self.mode == FunctionExecutionMode.CELL:
            columns = list(rows[0].keys()) if rows else []
            if len(columns) != 1:
                raise ValueError(f"CELL transformations take exactly one column, got {columns}")
            return [transformer.transform(row[columns[0]]) for row in rows]
        if self.mode == FunctionExecutionMode.PATIENT:
            result = transformer.transform(rows)
            results = result[0] if isinstance(result, tuple) else result
            if results is None:
                raise ValueError("transform returned None instead of patient results")
            if len(results) > len(rows):
                raise ValueError("transform must not return more results than the patient has rows")
            # a None result leaves the row untouched, so there is nothing to check
            return [r for r in results if r is not None]
        return [transformer.transform(row) for row in rows]

    def _check_results(self, results: list[Any]) -> list[str]:
        errors = []
        for i, result in enumerate(results):
            try:
                validate_value(self._single_value(result), self.goal)
            except ValueError as e:
                errors.append(f"result {i} ({result!r}): {e}")
        return errors

    @staticmethod
    def _to_rows(data: dict[str, object]) -> list[dict[str, Any]]:
        # through a DataFrame, as the transformation sees the data at runtime
        has_lists = any(isinstance(v, list) for v in data.values())
        return pd.DataFrame(data if has_lists else [data]).to_dict("records")

    @staticmethod
    def _typed(value: str, goal: DataTypeTransformationGoalDTO) -> Any:
        # generated values are strings; numbers and booleans are passed on typed, as read from a CSV
        if goal.options or goal.type not in (DataTypes.INT, DataTypes.FLOAT, DataTypes.BOOLEAN):
            return value
        return normalize_value(value, goal.type)

    @staticmethod
    def _single_value(result: Any) -> Any:
        if isinstance(result, dict):
            if len(result) != 1:
                raise ValueError(f"expected a single value, got a dict with keys {list(result.keys())}")
            return next(iter(result.values()))
        return result

    @staticmethod
    def _fail(message: str) -> TransformationFactoryTestResultDTO:
        return TransformationFactoryTestResultDTO(is_success=False, message=message)


def test_function(goal: DataTypeTransformationGoalDTO,
                  source_code: str,
                  data: Optional[dict[str, object]] = None,
                  sourceGoals: Optional[dict[str, DataTypeTransformationGoalDTO]] = None,
                  mode: FunctionExecutionMode = FunctionExecutionMode.ROW,
                  amount: int = 10) \
        -> TransformationFactoryTestResultDTO:
    try:
        tester = TransformationTester(goal, sourceGoals, mode, amount)
    except ValueError as e:
        return TransformationFactoryTestResultDTO(is_success=False, message=f"Invalid goal, {e}")
    return tester.test(source_code, data)

import re
from datetime import date, datetime

import pandas as pd
import pytest

from pyfedappwrap.generator.datatype_generator import DataTypeRandomGenerator
from pyfedappwrap.transformation.validate.datatype_dto import DataTypeTransformationGoalDTO, DataTypes, \
    DataTypeValidationDTO, DataTypeValidationType


def _dt(type_: DataTypes, options=None, **validations) -> DataTypeTransformationGoalDTO:
    return DataTypeTransformationGoalDTO(
        type=type_,
        options=options or [],
        validations=[
            DataTypeValidationDTO(name=DataTypeValidationType(k.upper()), validator=str(v), message="")
            for k, v in validations.items()
        ],
    )


def test_int_respects_min_max() -> None:
    values = DataTypeRandomGenerator(seed=1).generate_dummy_data(_dt(DataTypes.INT, min=5, max=9), 200)
    assert len(values) == 200
    assert all(5 <= int(v) <= 9 for v in values)


def test_float_respects_min_max() -> None:
    values = DataTypeRandomGenerator(seed=1).generate_dummy_data(_dt(DataTypes.FLOAT, min=-1.5, max=1.5), 200)
    assert all(-1.5 <= float(v) <= 1.5 for v in values)


def test_string_respects_length_and_pattern() -> None:
    gen = DataTypeRandomGenerator(seed=1)
    values = gen.generate_dummy_data(_dt(DataTypes.STRING, minlength=4, maxlength=6), 100)
    assert all(4 <= len(v) <= 6 and v.islower() for v in values)

    values = gen.generate_dummy_data(_dt(DataTypes.STRING, pattern=r"^\d{6}$"), 50)
    assert all(re.fullmatch(r"\d{6}", v) for v in values)


def test_options_win_over_type() -> None:
    values = DataTypeRandomGenerator(seed=1).generate_dummy_data(_dt(DataTypes.INT, options=["a", "b"]), 50)
    assert set(values) <= {"a", "b"}


@pytest.mark.parametrize("type_,check", [
    (DataTypes.BOOLEAN, lambda v: v in ("true", "false")),
    (DataTypes.DATE, lambda v: date.fromisoformat(v) is not None),
    (DataTypes.DATE_TIME, lambda v: datetime.fromisoformat(v) is not None),
    (DataTypes.CATEGORICAL, lambda v: 3 <= len(v) <= 8),
    (DataTypes.FILE, lambda v: re.fullmatch(r"[a-z]{8}\.txt", v)),
])
def test_other_types(type_, check) -> None:
    values = DataTypeRandomGenerator(seed=1).generate_dummy_data(_dt(type_), 30)
    assert all(check(v) for v in values)


def test_seed_is_reproducible() -> None:
    dt = _dt(DataTypes.FLOAT, min=0, max=10)
    assert DataTypeRandomGenerator(seed=7).generate_dummy_data(dt, 10) == \
           DataTypeRandomGenerator(seed=7).generate_dummy_data(dt, 10)


def test_rows_long_format_and_csv() -> None:
    gen = DataTypeRandomGenerator(seed=1)
    df = pd.DataFrame({
        "age": gen.generate_dummy_data(_dt(DataTypes.INT, min=18, max=99), 10),
        "note": ["a,b"] * 10,
    })
    rows = df.to_dict("records")
    assert len(rows) == 10 and set(rows[0]) == {"age", "note"}

    long_rows = gen.wide_format_to_long_format(rows)
    assert len(long_rows) == 20
    assert {r["name"] for r in long_rows} == {"age", "note"}
    assert all(1 <= int(r["patientId"]) <= 2 for r in long_rows)

    csv_text = df.to_csv(index=False)
    assert csv_text.splitlines()[0] == "age,note"
    assert '"a,b"' in csv_text

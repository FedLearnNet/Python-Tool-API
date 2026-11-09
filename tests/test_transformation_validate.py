from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from pyfedappwrap.generator.datatype_generator import DataTypeRandomGenerator
from pyfedappwrap.transformation.validate.datatype_dto import DataTypeTransformationGoalDTO, DataTypes, \
    DataTypeValidationDTO, DataTypeValidationType
from pyfedappwrap.transformation.validate.validate import is_valid_value, normalize_value, validate


def _dt(type_: DataTypes, options=None, **kwargs) -> DataTypeTransformationGoalDTO:
    flags = {k: kwargs.pop(k) for k in ("isRequired", "allowNullValues") if k in kwargs}
    return DataTypeTransformationGoalDTO(
        type=type_,
        options=options or [],
        validations=[
            DataTypeValidationDTO(name=DataTypeValidationType(k.upper()), validator=str(v), message="")
            for k, v in kwargs.items()
        ],
        **flags,
    )


@pytest.mark.parametrize("goal", [
    _dt(DataTypes.STRING, minlength=1, maxlength=5, pattern=r"[a-z]+"),
    _dt(DataTypes.INT, min=0, max=10),
    _dt(DataTypes.FLOAT, min=-1.5),
    _dt(DataTypes.DATE, min="2020-01-01", max="2021-01-01"),
    _dt(DataTypes.DATE_TIME, max="2021-01-01T12:00:00+02:00"),
    _dt(DataTypes.BOOLEAN),
])
def test_valid_goals(goal) -> None:
    validate(goal)


@pytest.mark.parametrize("goal,error", [
    (_dt(DataTypes.INT, minlength=1), "only be applied to STRING"),
    (_dt(DataTypes.STRING, pattern="[a-"), "Invalid PATTERN validator"),
    (_dt(DataTypes.STRING, maxlength=-1), "greater than or equal to 0"),
    (_dt(DataTypes.STRING, maxlength="x"), "valid integer"),
    (_dt(DataTypes.BOOLEAN, min=1), "only be applied to INT, FLOAT, DATE, DATE_TIME"),
    (_dt(DataTypes.INT, min="abc"), "valid number"),
    (_dt(DataTypes.DATE, min="2020-01-01T10:00:00"), "should have zero time"),
    (_dt(DataTypes.INT, min=10, max=1), "MIN 10 is greater than MAX 1"),
    (_dt(DataTypes.STRING, minlength=5, maxlength=2), "MINLENGTH 5 is greater"),
])
def test_invalid_goals(goal, error) -> None:
    with pytest.raises(ValueError, match=error):
        validate(goal)


def test_duplicate_validation_is_invalid() -> None:
    goal = _dt(DataTypes.INT, min=1)
    goal.validations.append(goal.validations[0])
    with pytest.raises(ValueError, match="defined more than once: MIN"):
        validate(goal)


@pytest.mark.parametrize("value,goal,valid", [
    (5, _dt(DataTypes.INT, min=0, max=10), True),
    ("5", _dt(DataTypes.INT, min=0, max=10), True),
    (5.0, _dt(DataTypes.INT), True),
    (5.5, _dt(DataTypes.INT), False),
    (11, _dt(DataTypes.INT, max=10), False),
    (True, _dt(DataTypes.INT), False),
    ("1.5", _dt(DataTypes.FLOAT, min=1), True),
    ("x", _dt(DataTypes.FLOAT), False),
    ("TRUE", _dt(DataTypes.BOOLEAN), True),
    ("yes", _dt(DataTypes.BOOLEAN), False),
    ("abc", _dt(DataTypes.STRING, minlength=2, maxlength=3, pattern="[a-z]+"), True),
    ("abcd", _dt(DataTypes.STRING, maxlength=3), False),
    ("ab1", _dt(DataTypes.STRING, pattern="[a-z]+"), False),
    ({"a": 1}, _dt(DataTypes.STRING), False),
    ("2020-06-01", _dt(DataTypes.DATE, min="2020-01-01", max="2021-01-01"), True),
    ("2019-06-01", _dt(DataTypes.DATE, min="2020-01-01"), False),
    ("2020-06-01T10:00:00", _dt(DataTypes.DATE), False),
    ("2021-01-01T11:00:00+02:00", _dt(DataTypes.DATE_TIME, max="2021-01-01T10:00:00Z"), True),
    ("b", _dt(DataTypes.CATEGORICAL, options=["a", "b"]), True),
    ("c", _dt(DataTypes.CATEGORICAL, options=["a", "b"]), False),
    (True, _dt(DataTypes.BOOLEAN, options=["true"]), True),
    (None, _dt(DataTypes.INT), True),
    (float("nan"), _dt(DataTypes.INT), True),
    (None, _dt(DataTypes.INT, isRequired=True), False),
    ("", _dt(DataTypes.STRING, allowNullValues=False), False),
])
def test_value_validation(value, goal, valid) -> None:
    assert is_valid_value(value, goal) is valid


def test_normalize_and_instant() -> None:
    assert normalize_value("42", DataTypes.INT) == 42
    assert normalize_value("2020-01-02", DataTypes.DATE) == date(2020, 1, 2)
    assert normalize_value("2020-01-01T02:00:00+02:00", DataTypes.DATE_TIME) == datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert normalize_value("2020-01-01T02:00:00", DataTypes.DATE_TIME).tzinfo == timezone.utc
    assert normalize_value(86400, DataTypes.DATE) == date(1970, 1, 2)
    assert normalize_value(str(86_400_000 * 1000), DataTypes.DATE_TIME) == datetime(1972, 9, 27, tzinfo=timezone.utc)
    assert normalize_value(np.int64(3), DataTypes.INT) == 3
    assert normalize_value(np.True_, DataTypes.BOOLEAN) is True


def test_generator_rejects_invalid_goal() -> None:
    with pytest.raises(ValueError, match="column 'age'"):
        DataTypeRandomGenerator().generate_data({"age": _dt(DataTypes.INT, min=10, max=1)})


@pytest.mark.parametrize("goal", [
    _dt(DataTypes.DATE, min="2030-01-01", max="2030-02-01"),
    _dt(DataTypes.DATE, min="2030-01-01"),
    _dt(DataTypes.DATE_TIME, max="1960-01-01T00:00:00"),
])
def test_generator_respects_date_bounds(goal) -> None:
    values = DataTypeRandomGenerator(seed=1).generate_dummy_data(goal, 50)
    assert all(is_valid_value(v, goal) for v in values)

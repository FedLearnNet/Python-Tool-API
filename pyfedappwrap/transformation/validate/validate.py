import re
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from pydantic import ValidationError

from pyfedappwrap.transformation.validate.constants import ADAPTERS, APPLICABLE_TYPES, \
    LENGTH_ADAPTER
from pyfedappwrap.transformation.validate.datatype_dto import (
    DataTypes,
    DataTypeTransformationGoalDTO,
    DataTypeValidationDTO,
    DataTypeValidationType,
)


def validate(goal: DataTypeTransformationGoalDTO) -> None:
    names = [v.name for v in goal.validations]
    duplicates = sorted({n.value for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"Validations defined more than once: {', '.join(duplicates)}")

    rules = {v.name: parse_rule(v, goal.type) for v in goal.validations}
    raw = {v.name: v.validator for v in goal.validations}
    for lower, upper in ((DataTypeValidationType.MIN, DataTypeValidationType.MAX),
                         (DataTypeValidationType.MINLENGTH, DataTypeValidationType.MAXLENGTH)):
        if lower in rules and upper in rules and rules[lower] > rules[upper]:
            raise ValueError(
                f"{lower.value} {raw[lower]} is greater than {upper.value} {raw[upper]}")


def parse_rule(validation: DataTypeValidationDTO, data_type: DataTypes) -> Any:
    name, validator = validation.name, validation.validator
    if data_type not in APPLICABLE_TYPES[name]:
        allowed = ", ".join(t.value for t in APPLICABLE_TYPES[name])
        raise ValueError(f"{name.value} validation can only be applied to {allowed}, "
                         f"but got: {data_type.value}")
    if not validator:
        raise ValueError(f"{name.value} validation needs a validator value")
    try:
        if name in (DataTypeValidationType.MINLENGTH, DataTypeValidationType.MAXLENGTH):
            return LENGTH_ADAPTER.validate_python(validator)
        if name == DataTypeValidationType.PATTERN:
            return re.compile(validator)
        return normalize_value(validator,
                               DataTypes.FLOAT if data_type == DataTypes.INT else data_type)
    except (ValueError, re.error) as e:
        raise ValueError(f"Invalid {name.value} validator {validator!r}: {_message(e)}") from None


def validate_value(value: Any, goal: DataTypeTransformationGoalDTO) -> None:
    if is_empty(value):
        if goal.isRequired:
            raise ValueError("Value is required")
        if not goal.allowNullValues:
            raise ValueError("Null values are not allowed")
        return

    if goal.options:
        option = ("true" if value else "false") if isinstance(value, (bool, np.bool_)) else str(
            value)
        if option not in goal.options:
            raise ValueError(f"Value {value!r} is not one of the allowed options {goal.options}")
        return

    normalized = normalize_value(value, goal.type)
    for validation in goal.validations:
        rule = parse_rule(validation, goal.type)
        name = validation.name
        if name == DataTypeValidationType.MINLENGTH and len(normalized) < rule:
            raise ValueError(f"Value must be at least {rule} characters long")
        if name == DataTypeValidationType.MAXLENGTH and len(normalized) > rule:
            raise ValueError(f"Value must be at most {rule} characters long")
        if name == DataTypeValidationType.PATTERN and not rule.fullmatch(normalized):
            raise ValueError(f"Value {normalized!r} does not match the pattern {rule.pattern}")
        if name == DataTypeValidationType.MIN and normalized < rule:
            raise ValueError(f"Value {value!r} must be at least {validation.validator}")
        if name == DataTypeValidationType.MAX and normalized > rule:
            raise ValueError(f"Value {value!r} must be at most {validation.validator}")


def is_valid_value(value: Any, goal: DataTypeTransformationGoalDTO) -> bool:
    try:
        validate_value(value, goal)
        return True
    except ValueError:
        return False


def normalize_value(value: Any, data_type: DataTypes) -> Any:
    if is_empty(value):
        return None
    if not pd.api.types.is_scalar(value):
        raise ValueError(f"Value {value!r} of type {type(value).__name__} is not a single value")

    if data_type in (DataTypes.STRING, DataTypes.CATEGORICAL, DataTypes.FILE):
        return str(value)
    if data_type == DataTypes.BOOLEAN:
        text = str(value).strip().lower()
        if text not in ("true", "false"):
            raise ValueError(f"Value {value!r} is not a valid BOOLEAN, expected true or false")
        return text == "true"
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"Value {value!r} is not a valid {data_type.value}")
    try:
        normalized = ADAPTERS[data_type].validate_python(value)
    except ValidationError as e:
        raise ValueError(
            f"Value {value!r} is not a valid {data_type.value}: {_message(e)}") from None
    if isinstance(normalized, datetime):
        normalized = normalized.replace(tzinfo=timezone.utc) if normalized.tzinfo is None \
            else normalized.astimezone(timezone.utc)
    return normalized


def is_empty(value: Any) -> bool:
    if isinstance(value, str):
        return value == ""
    return pd.api.types.is_scalar(value) and pd.isna(value)


def _message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return error.errors()[0]["msg"]
    return str(error)

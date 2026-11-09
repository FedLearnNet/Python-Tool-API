from typing import Any

import numpy as np
import pandas as pd
from pydantic import ValidationError


def value_to_str(value: Any) -> str:
    return str(value).lower() if isinstance(value, (bool, np.bool_)) else str(value)


def is_empty(value: Any) -> bool:
    if isinstance(value, str):
        return value == ""
    return pd.api.types.is_scalar(value) and pd.isna(value)


def validation_error_message(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return error.errors()[0]["msg"]
    return str(error)

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class DataTypeValidationType(str, Enum):
    MINLENGTH = "MINLENGTH"
    MAXLENGTH = "MAXLENGTH"
    PATTERN = "PATTERN"
    MIN = "MIN"
    MAX = "MAX"


class DataTypeValidationDTO(BaseModel):
    name: DataTypeValidationType
    validator: str
    message: str


class DataTypes(str, Enum):
    INT = "INT"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    STRING = "STRING"
    FILE = "FILE"
    DATE = "DATE"
    DATE_TIME = "DATE_TIME"
    CATEGORICAL = "CATEGORICAL"


class DataTypeTransformationGoalDTO(BaseModel):
    options: List[str] = Field(default_factory=list)
    validations: List[DataTypeValidationDTO] = Field(default_factory=list)
    type: DataTypes
    isRequired: bool = False
    allowNullValues: bool = True

from enum import Enum


class FunctionExecutionMode(str, Enum):
    ROW = "ROW"
    CELL = "CELL"
    PATIENT = "PATIENT"
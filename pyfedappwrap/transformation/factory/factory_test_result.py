from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from pyfedappwrap.transformation.transformation_mode import FunctionExecutionMode
from pyfedappwrap.transformation.validate.datatype_dto import DataTypeTransformationGoalDTO


class TransformationSampleDTO(BaseModel):
    input: Any = None
    output: Any = None
    error: Optional[str] = None


class TransformationFactoryTestResultDTO(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    is_success: bool
    message: str
    input_keys: list[str] = []
    return_keys: list[str] = []
    samples: list[TransformationSampleDTO] = []


class TransformationTestCaseDTO(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    mode: FunctionExecutionMode
    goal: DataTypeTransformationGoalDTO
    source_goals: Optional[dict[str, DataTypeTransformationGoalDTO]] = None
    data: Optional[dict[str, list[Any]]] = None

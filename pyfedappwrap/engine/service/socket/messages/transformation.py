from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from pyfedappwrap.transformation.factory.factory_test_result import TransformationFactoryTestResultDTO
from pyfedappwrap.transformation.transformation_mode import FunctionExecutionMode
from pyfedappwrap.transformation.validate.datatype_dto import DataTypeTransformationGoalDTO


class TransformationCheckDTO(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    request_id: str
    body: str
    mode: FunctionExecutionMode
    goal: DataTypeTransformationGoalDTO
    source_goals: Optional[dict[str, DataTypeTransformationGoalDTO]] = None
    data: Optional[dict[str, list[Any]]] = None


class TransformationCheckResultDTO(TransformationFactoryTestResultDTO):
    request_id: str
    output: str = ""

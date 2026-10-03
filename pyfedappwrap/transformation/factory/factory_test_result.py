from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


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

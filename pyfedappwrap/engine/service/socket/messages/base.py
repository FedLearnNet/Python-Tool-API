import abc
from typing import Generic, TypeVar, Annotated
from pydantic import BaseModel, Field, ConfigDict

from pyfedappwrap.engine.enums.test_embed_states import RunType, TestEmbedEnum

M = TypeVar('M')

NOT_DEFINED_TYPE: RunType = Field(description="The type of run",
                                    default=RunType.NOT_DEFINED,
                                    alias='runType')

class BaseSocketMessage(BaseModel, abc.ABC, Generic[M]):
    model_config = ConfigDict(populate_by_name=True)

    message: Annotated[M, Field(description="The message payload", alias='message')]
    run_type: Annotated[RunType, Field(description="The type of run", alias='runType')]
    type: Annotated[TestEmbedEnum, Field(description="The embedded enum type", alias='type')]

    def to_json(self):
        return self.model_dump_json(by_alias=True)
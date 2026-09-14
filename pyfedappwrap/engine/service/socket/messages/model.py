from typing import Annotated

from pydantic import BaseModel, Field, ConfigDict

from pyfedappwrap.engine.enums.test_embed_states import TestEmbedEnum
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage


class ModelFileDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True,
                              protected_namespaces=())
    model_path: Annotated[str, Field(description="Path to the file", alias='modelPath')]
    name: Annotated[str, Field(description="Name of the file")]
    model_params: Annotated[
        bytes, Field(description="Binary data of the file", alias='modelParams')]


class ModelRunFileDTO(ModelFileDTO):
    run_id: Annotated[int, Field(description="Identifier for the run", alias='runId')]


class SendModelFileDTO(BaseSocketMessage[ModelRunFileDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.SEND_MODEL, description="Type of the message")

    def to_json(self):
        return self.model_dump_json(by_alias=True)
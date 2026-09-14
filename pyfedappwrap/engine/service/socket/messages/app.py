from typing import Any, Annotated

from pydantic import BaseModel, Field

from pyfedappwrap.engine.enums.test_embed_states import TestEmbedEnum
from pyfedappwrap.engine.federated.models import FLNetDataNoticeDTO
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.worker.run_dto import UpdateTestRunDTO, FinishRunDTO


class AppTaskMessage(BaseModel):
    task: Annotated[str, Field(description="The task to be executed")]
    body: Annotated[Any, Field(description="The body of the task")]


class SendUpdateRunDTO(BaseSocketMessage[UpdateTestRunDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.UPDATE_RUN,
                                description="Type of the message")


class SendFinishRunDTO(BaseSocketMessage[FinishRunDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.FINISH_RUN,
                                description="Type of the message")


class SendFederatedDataNoticeDTO(BaseSocketMessage[FLNetDataNoticeDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.FEDERATED_DATA_NOTICE,
                                description="Type of the message")

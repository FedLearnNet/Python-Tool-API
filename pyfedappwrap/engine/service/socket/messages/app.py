from typing import Any, Annotated

from pydantic import BaseModel, Field

from pyfedappwrap.engine.enums.test_embed_states import WebsocketMessageTypes
from pyfedappwrap.engine.federated.models import FLNetDataNoticeDTO
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.worker.run_dto import UpdateTestRunDTO, FinishRunDTO


class AppTaskMessage(BaseModel):
    task: Annotated[WebsocketMessageTypes, Field(description="The task to be executed")]
    body: Annotated[Any, Field(description="The body of the task")]


class SendUpdateRunDTO(BaseSocketMessage[UpdateTestRunDTO]):
    type: WebsocketMessageTypes = Field(default=WebsocketMessageTypes.UPDATE_RUN,
                                        description="Type of the message")


class SendFinishRunDTO(BaseSocketMessage[FinishRunDTO]):
    type: WebsocketMessageTypes = Field(default=WebsocketMessageTypes.FINISH_RUN,
                                        description="Type of the message")


class SendFederatedDataNoticeDTO(BaseSocketMessage[FLNetDataNoticeDTO]):
    type: WebsocketMessageTypes = Field(default=WebsocketMessageTypes.FEDERATED_DATA_NOTICE,
                                        description="Type of the message")

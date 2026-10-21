from pydantic import Field

from pyfedappwrap.engine.config.config import FederatedAppDTO
from pyfedappwrap.engine.enums.test_embed_states import WebsocketMessageTypes, RunType
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage, NOT_DEFINED_TYPE


class SendConfigChangedDTO(BaseSocketMessage[FederatedAppDTO]):
    type: WebsocketMessageTypes = Field(default=WebsocketMessageTypes.CONFIG_CHANGED,
                                        description="Type of the message")
    run_type: RunType = NOT_DEFINED_TYPE

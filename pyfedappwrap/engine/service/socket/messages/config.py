from pydantic import Field

from pyfedappwrap.engine.config.config import FederatedAppDTO
from pyfedappwrap.engine.enums.test_embed_states import TestEmbedEnum, RunType
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage, NOT_DEFINED_TYPE


class SendConfigChangedDTO(BaseSocketMessage[FederatedAppDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.CONFIG_CHANGED,
                                description="Type of the message")
    run_type: RunType = NOT_DEFINED_TYPE

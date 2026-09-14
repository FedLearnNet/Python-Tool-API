from pydantic import Field

from pyfedappwrap.engine.enums.test_embed_states import TestEmbedEnum, RunType
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage, NOT_DEFINED_TYPE
from pyfedappwrap.engine.service.socket.messages.monitor import PerformanceDTO



class ClientPerformanceDTO(BaseSocketMessage[PerformanceDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.APP_PERFORMANCE,
                                description="Type of the message")
    run_type: RunType = NOT_DEFINED_TYPE


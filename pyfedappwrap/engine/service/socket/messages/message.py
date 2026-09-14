from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, ConfigDict

from pyfedappwrap.engine.enums.test_embed_states import TestEmbedEnum, RunType
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage, NOT_DEFINED_TYPE
from pyfedappwrap.engine.service.socket.messages.monitor import ConsoleStdOutDTO


class RunMessageTypes(Enum):
    METRIC = "METRIC"
    LOG = "LOG"

    def __str__(self):
        return self.value.upper()


class RunMessageDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    process: Annotated[str, Field(description="The process")]
    type: Annotated[RunMessageTypes, Field(description="The type of the message")]
    message: Annotated[str, Field(description="the message itself")]
    run_id: Annotated[int, Field(description="the runId", alias='runId')]
    # for federated runs, the workerId is the participantId
    # for other types, this isnt used yet, but could be
    worker_id: Annotated[
        str | None, Field(default=None, description="Worker/Participant ID", alias='workerId')]


class TestRunMessageLogDTO(RunMessageDTO):
    type: RunMessageTypes = Field(default=RunMessageTypes.LOG, description="Type of the message")
    severity: Annotated[str, Field(description="Severity of the log")]
    message: Annotated[str, Field(description="The message")]
    caller: Annotated[str | None, Field(description="Who called the log")]
    stack_trace: Annotated[str | None, Field(description="the runId", alias='stackTrace')]
    group: Annotated[str | None, Field(description="Group of the log")]

    


class TestRunMessageMetricDTO(RunMessageDTO):
    type: RunMessageTypes = Field(default=RunMessageTypes.METRIC, description="Type of the message")

    metric: Annotated[str, Field(description="The metric name")]
    value: Annotated[str, Field(description="The value of the metric")]
    x: Annotated[str, Field(description="X axis for the metric", alias='x')]
    x_unit: Annotated[str, Field(description="The X unit for the metric", alias='xUnit')]



class SendMetricDTO(BaseSocketMessage[TestRunMessageMetricDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.LOG_METRIC, description="Type of the message")

class SendLogDTO(BaseSocketMessage[TestRunMessageLogDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.LOG_MESSAGE, description="Type of the message")



class SendConsoleMessage(BaseSocketMessage[ConsoleStdOutDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.CONSOLE_MESSAGE, description="Type of the message")
    run_type: RunType = NOT_DEFINED_TYPE

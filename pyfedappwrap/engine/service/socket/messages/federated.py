"""Socket message DTOs for frontend-triggered federated test runs."""
from __future__ import annotations

from typing import Annotated, Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from pyfedappwrap.engine.config.defaults import DEFAULT_APP_COMM_TIMEOUT
from pyfedappwrap.engine.enums.test_embed_states import RunType, TestEmbedEnum
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage


class FederatedParticipantLocalConfigDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    base_dir: Annotated[Optional[str], Field(default=None, alias="baseDir")]
    data_dir: Annotated[Optional[str], Field(default=None, alias="dataDir")]
    output_dir: Annotated[Optional[str], Field(default=None, alias="outputDir")]


class FederatedRunConfigDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    poll_interval: Annotated[Optional[float], Field(default=None, alias="pollInterval")]
    timeout: Optional[float] = DEFAULT_APP_COMM_TIMEOUT
    max_polls: Annotated[Optional[int], Field(default=None, alias="maxPolls")]
    channel: Optional[str] = None

    # Relay topology for real (non-simulated) runs, where the payload contains only this app
    # instance's participant and the full client list cannot be derived from `participants`.
    client_id: Annotated[Optional[str], Field(default=None, alias="clientId")]
    coordinator_id: Annotated[Optional[str], Field(default=None, alias="coordinatorId")]
    order_client_ids: Annotated[Optional[List[str]], Field(default=None, alias="orderClientIds")]
    max_num_clients: Annotated[Optional[int], Field(default=None, alias="maxNumClients")]

class FederatedParticipantConfigDTO(BaseModel):
    """Participant as sent in the create payload and returned by the backend."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    participant_id: Annotated[str, Field(alias="participantId")]
    role: str
    config: Optional[FederatedParticipantLocalConfigDTO] = None
    hyper_params: Annotated[Optional[dict[str, Any]], Field(default=None, alias="hyperParams")]
    input_file_paths: Annotated[
        Optional[dict[str, str]], Field(default=None, alias="inputFilePaths")]


class FederatedTestRunCreateDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: int
    status: Optional[str] = None
    error: Optional[str] = None
    current_round: Annotated[Optional[int], Field(default=None, alias="currentRound")]
    federated_app_version_id: Annotated[
        Optional[int], Field(default=None, alias="federatedAppVersionId")]
    federated_app_id: Annotated[Optional[int], Field(default=None, alias="federatedAppId")]
    start_aggregator: Annotated[Optional[bool], Field(default=None, alias="startAggregator")]
    total_rounds: Annotated[Optional[int], Field(default=None, alias="totalRounds")]
    config: Optional[FederatedRunConfigDTO] = None
    output_data: Annotated[Optional[dict[str, Any]], Field(default=None, alias="outputData")]
    participants: List[FederatedParticipantConfigDTO] = []


class FederatedParticipantUpdateDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    federated_run_id: Annotated[int, Field(alias="federatedRunId")]
    participant_id: Annotated[str, Field(alias="participantId")]
    status: Optional[str] = None
    current_round: Annotated[Optional[int], Field(default=None, alias="currentRound")]
    messages_received: Annotated[Optional[int], Field(default=None, alias="messagesReceived")]
    messages_sent: Annotated[Optional[int], Field(default=None, alias="messagesSent")]
    waiting_for: Annotated[Optional[List[str]], Field(default=None, alias="waitingFor")]


class FederatedRoundMessageCreateDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    federated_run_id: Annotated[int, Field(alias="federatedRunId")]
    direction: str  # "SEND" or "RECEIVE"
    round: Optional[int] = None
    from_participant: Annotated[Optional[str], Field(default=None, alias="fromParticipant")]
    to_participant: Annotated[Optional[str], Field(default=None, alias="toParticipant")]
    communication_id: Annotated[Optional[str], Field(default=None, alias="communicationId")]
    payload_preview: Annotated[Optional[str], Field(default=None, alias="payloadPreview")]


class SendFederatedUpdateRunDTO(BaseSocketMessage[FederatedTestRunCreateDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.UPDATE_FEDERATED_RUN)
    run_type: RunType = Field(default=RunType.FEDERATED_RUN, alias="runType")


class SendFederatedFinishRunDTO(BaseSocketMessage[FederatedTestRunCreateDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.FINISH_FEDERATED_RUN)
    run_type: RunType = Field(default=RunType.FEDERATED_RUN, alias="runType")


class SendFederatedParticipantUpdateDTO(BaseSocketMessage[FederatedParticipantUpdateDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.FEDERATED_PARTICIPANT_UPDATE)
    run_type: RunType = Field(default=RunType.FEDERATED_RUN, alias="runType")


class SendFederatedRoundMessageDTO(BaseSocketMessage[FederatedRoundMessageCreateDTO]):
    type: TestEmbedEnum = Field(default=TestEmbedEnum.FEDERATED_ROUND_MESSAGE)
    run_type: RunType = Field(default=RunType.FEDERATED_RUN, alias="runType")

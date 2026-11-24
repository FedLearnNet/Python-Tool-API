"""Socket message DTOs for frontend-triggered federated test runs."""
from __future__ import annotations

from typing import Annotated, Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from pyfedappwrap.engine.config.defaults import DEFAULT_APP_COMM_TIMEOUT
from pyfedappwrap.engine.enums.test_embed_states import RunType, WebsocketMessageTypes
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

    # Flower-only (CommunicationEngine.FLOWER): the platform's directly-exposed SuperLink
    # address:port and its TLS CA cert - what #13's Task 4 (Platform -> Client Provisioning)
    # carries to a clinic's SuperNode, in place of a relay channel.
    superlink_address: Annotated[Optional[str], Field(default=None, alias="superlinkAddress")]
    # CA certificate CONTENT (PEM text), not a path - Learning APIs caches and forwards whatever
    # the platform's aggregator last reported (see FederatedTestRunCreateDTO.ca_certificate
    # below); FederatedWorkerManager writes it to a local file itself before passing a path into
    # FlowerRunLifecycle.start_as_client (see certs.write_ca_certificate). May be absent (the
    # platform's very first Flower run ever, before any CA has been generated and cached) - the
    # client then falls back to `--insecure`, same as today, until a later run has one to send.
    ca_certificate: Annotated[Optional[str], Field(default=None, alias="caCertificate")]
    # Platform aggregator only, never sent to a clinic: the private key of the stored CA above
    # (PEM, PKCS8), so the aggregator signs its new leaf cert with the same CA the run's clinics
    # were already given, instead of generating a new CA every run (see certs.py).
    ca_private_key: Annotated[Optional[str], Field(default=None, alias="caPrivateKey", repr=False)]
    # Retained for a local path provided directly (e.g. local testing) without going through the
    # ca_certificate content field above.
    superlink_root_certificates_path: Annotated[
        Optional[str], Field(default=None, alias="superlinkRootCertificatesPath")]
    supernode_auth_private_key_path: Annotated[
        Optional[str], Field(default=None, alias="supernodeAuthPrivateKeyPath")]

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
    distributed_test: bool = Field(default=False, alias="distributedTest")
    status: Optional[str] = None
    error: Optional[str] = None
    current_round: Annotated[Optional[int], Field(default=None, alias="currentRound")]
    federated_app_version_id: Annotated[
        Optional[int], Field(default=None, alias="federatedAppVersionId")]
    federated_app_id: Annotated[Optional[int], Field(default=None, alias="federatedAppId")]
    start_aggregator: Annotated[Optional[bool], Field(default=None, alias="startAggregator")]
    aggregator_only: Annotated[Optional[bool], Field(default=None, alias="aggregatorOnly")]
    total_rounds: Annotated[Optional[int], Field(default=None, alias="totalRounds")]
    config: Optional[FederatedRunConfigDTO] = None
    output_data: Annotated[Optional[dict[str, Any]], Field(default=None, alias="outputData")]
    participants: List[FederatedParticipantConfigDTO] = []
    # Flower-only: a CA cert and its private key the platform aggregator has just generated
    # (none was stored yet, or the stored one was about to expire), reported up once (see
    # FederatedStatusReporter.report_ca_certificate) so Learning APIs stores both, hands the cert
    # to clinics and the pair back to the aggregator on later runs. Absent on every other message.
    ca_certificate: Annotated[Optional[str], Field(default=None, alias="caCertificate")]
    ca_private_key: Annotated[Optional[str], Field(default=None, alias="caPrivateKey", repr=False)]
    # "FL_NET" (default, for backward compatibility with senders that predate this field) or
    # "FLOWER" - which engine's path FederatedWorkerManager dispatches this start to. Kept as a
    # bare tag on the existing message (not a new message type) per Julian's review: "can't the
    # logic of START_FEDERATED_RUN not just have an if else statement based on the communication
    # engine?" - see Flower_Integration_Plan.md's resolved #13<->#11 contract.
    communication_engine: Annotated[str, Field(default="FL_NET", alias="communicationEngine")]


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


class FlowerSupernodeKeyDTO(BaseModel):
    """A clinic SuperNode's OpenSSH EC public key, on its way to the platform's aggregator."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    request_id: Annotated[str, Field(alias="requestId")]
    public_key: Annotated[str, Field(alias="publicKey")]
    # Set by global (the clinic's participant id) so `flwr supernode list` shows who is who.
    name: Optional[str] = None


class FlowerSupernodeRegisteredDTO(BaseModel):
    """The aggregator's answer to a FlowerSupernodeKeyDTO, on its way back to the clinic."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    request_id: Annotated[str, Field(alias="requestId")]
    success: bool
    error: Optional[str] = None


class SendFlowerSupernodeKeyDTO(BaseSocketMessage[FlowerSupernodeKeyDTO]):
    type: WebsocketMessageTypes = Field(default=WebsocketMessageTypes.FLOWER_SUPERNODE_KEY)
    run_type: RunType = Field(default=RunType.FEDERATED_RUN, alias="runType")


class SendFlowerSupernodeRegisteredDTO(BaseSocketMessage[FlowerSupernodeRegisteredDTO]):
    type: WebsocketMessageTypes = Field(default=WebsocketMessageTypes.FLOWER_SUPERNODE_REGISTERED)
    run_type: RunType = Field(default=RunType.FEDERATED_RUN, alias="runType")


class SendFederatedUpdateRunDTO(BaseSocketMessage[FederatedTestRunCreateDTO]):
    type: WebsocketMessageTypes = Field(default=WebsocketMessageTypes.UPDATE_FEDERATED_RUN)
    run_type: RunType = Field(default=RunType.FEDERATED_RUN, alias="runType")


class SendFederatedFinishRunDTO(BaseSocketMessage[FederatedTestRunCreateDTO]):
    type: WebsocketMessageTypes = Field(default=WebsocketMessageTypes.FINISH_FEDERATED_RUN)
    run_type: RunType = Field(default=RunType.FEDERATED_RUN, alias="runType")


class SendFederatedParticipantUpdateDTO(BaseSocketMessage[FederatedParticipantUpdateDTO]):
    type: WebsocketMessageTypes = Field(default=WebsocketMessageTypes.FEDERATED_PARTICIPANT_UPDATE)
    run_type: RunType = Field(default=RunType.FEDERATED_RUN, alias="runType")


class SendFederatedRoundMessageDTO(BaseSocketMessage[FederatedRoundMessageCreateDTO]):
    type: WebsocketMessageTypes = Field(default=WebsocketMessageTypes.FEDERATED_ROUND_MESSAGE)
    run_type: RunType = Field(default=RunType.FEDERATED_RUN, alias="runType")

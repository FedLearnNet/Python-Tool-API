from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pyfedappwrap.engine.config.system_config import FLNetDPSettings, FLNetSMPCSettings


class FederatedParticipantType(Enum):
    CLIENT = "CLIENT"
    AGGREGATOR = "AGGREGATOR"


class FLNetBaseDTO(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


class FLNetMessageMetaDTO(FLNetBaseDTO):
    communication_id: str = Field(alias="communicationId")
    sender: str = Field(alias="fromClientId")
    from_aggregator: Optional[str] = Field(default=None, alias="fromAggregator")
    to_aggregator: Optional[str] = Field(default=None, alias="toAggregator")
    time_arrived: datetime = Field(default_factory=datetime.now, alias="timeArrived")
    extras: dict[str, Any] = Field(default_factory=dict)


class FLNetDataPackageDTO(FLNetBaseDTO):
    """Package containing data and its metadata."""
    data: Any
    meta: FLNetMessageMetaDTO

    @property
    def sender(self) -> str:
        return self.meta.sender

    @property
    def communication_id(self) -> str:
        return self.meta.communication_id


# ── Send request metadata DTOs (multipart form) ───────────────────────────────

class FLNetSendDataToAggregatorMetadataDTO(FLNetBaseDTO):
    """Metadata part of the multipart POST /send-data-to-aggregator request."""
    app_key: str = Field(alias="appKey")
    channel: str
    serialization_used: str = Field(default="json", alias="serializationUsed")
    to_aggregator: str = Field(alias="toAggregator")
    communication_id: Optional[str] = Field(default=None, alias="communicationId")
    smpc: Optional[FLNetSMPCSettings] = None
    dp: Optional[FLNetDPSettings] = None

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


class FLNetSendDataToClientsMetadataDTO(FLNetBaseDTO):
    """Metadata part of the multipart POST /send-data-to-clients request."""
    app_key: str = Field(alias="appKey")
    channel: str
    serialization_used: str = Field(default="json", alias="serializationUsed")
    to: Optional[list[str]] = Field(default_factory=list)
    from_aggregator: Optional[str] = Field(default=None, alias="fromAggregator")
    communication_id: str = Field(alias="communicationId")  # required, never auto
    dp: Optional[FLNetDPSettings] = None

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


# ── Receive request DTOs (JSON body) ─────────────────────────────────────────

class FLNetReceiveDataFromAggregatorRequestDTO(FLNetBaseDTO):
    """JSON body for POST /receive-data-from-aggregator."""
    app_key: str = Field(alias="appKey")
    channel: str
    serialization_format: str = Field(default="json", alias="serializationFormat")
    from_aggregator: str = Field(alias="fromAggregator")
    communication_id: Optional[str] = Field(default=None, alias="communicationId")

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


class FLNetReceiveDataFromClientsRequestDTO(FLNetBaseDTO):
    """JSON body for POST /receive-data-from-clients."""
    app_key: str = Field(alias="appKey")
    channel: str
    serialization_format: str = Field(default="json", alias="serializationFormat")
    to_aggregator: Optional[str] = Field(default=None, alias="toAggregator")
    communication_id: Optional[str] = Field(default=None, alias="communicationId")
    from_client_ids: list[str] = Field(default_factory=list, alias="fromClientIds")
    min_packages: int = Field(default=1, alias="minPackages")

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


# ── Receive response DTOs ─────────────────────────────────────────────────────

class FLNetReceiveSetupResponseDTO(FLNetBaseDTO):
    """Response from /receive-setup endpoint."""
    aggregator_id: Optional[str] = Field(default=None, alias="aggregatorId")
    client_order: list[str] = Field(default_factory=list, alias="clientOrder")
    max_num_clients: int = Field(default=0, alias="maxNumClients")

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


class FLNetReceiveDataResponseMetaDTO(FLNetBaseDTO):
    """Metadata from a received data package (camelCase from server)."""
    from_client_id: str = Field(alias="fromClientId")
    communication_id: str = Field(alias="communicationId")
    time_arrived: datetime = Field(alias="timeArrived")
    from_aggregator: Optional[str] = Field(default=None, alias="fromAggregator")
    to_aggregator: Optional[str] = Field(default=None, alias="toAggregator")

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


class FLNetReceiveDataResponseDTO(FLNetBaseDTO):
    """Single message body returned by /receive-data-from-aggregator or within
    a grouped map from /receive-data-from-clients."""
    meta: FLNetReceiveDataResponseMetaDTO
    data: Any


# ── Notice ────────────────────────────────────────────────────────────────────

class FLNetDataNoticeDTO(FLNetBaseDTO):
    recipient_id: str
    sender_id: Optional[str] = None
    communication_id: Optional[str] = None


# ── Local test config ─────────────────────────────────────────────────────────

class FLNetLocalParticipantConfigDTO(FLNetBaseDTO):
    participant_id: str
    role: FederatedParticipantType
    base_dir: Path
    data_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    hyper_params: dict[str, Any] = Field(default_factory=dict)
    input_file_paths: dict[str, str] = Field(default_factory=dict)

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value):
        if isinstance(value, FederatedParticipantType):
            return value
        if isinstance(value, str):
            return value.upper()
        return value


class FLNetLocalTestConfigDTO(FLNetBaseDTO):
    participants: list[FLNetLocalParticipantConfigDTO]
    poll_interval: float = 0.01
    timeout: float = 5.0
    max_polls: int = 500
    start_aggregator: bool = True
    channel: str = "local-test"
    use_external_controller: bool = False
    controller_url: Optional[str] = None
    simulate_participants_locally: bool = True
    # Relay topology overrides for real runs: the payload contains only this app instance's
    # participant, so the aggregator id and the full client list must come from the run config
    # (relay coordinatorId / orderClientIds) instead of being derived from `participants`.
    aggregator_id_override: Optional[str] = None
    client_ids_override: Optional[list[str]] = None

    @property
    def app_key(self) -> str:
        from pyfedappwrap.engine.config.system_config import system_settings
        return system_settings.app_key or "LOCAL_FLNET_TEST"

    @property
    def aggregator_id(self) -> str:
        if self.aggregator_id_override:
            return self.aggregator_id_override
        aggregator = next((p.participant_id for p in self.participants
                           if p.role == FederatedParticipantType.AGGREGATOR), None)
        if aggregator is None:
            raise ValueError(
                "No aggregator id available: the participants payload contains no AGGREGATOR and "
                "the run config provides no coordinatorId."
            )
        return aggregator

    @property
    def aggregator_participant(self) -> FLNetLocalParticipantConfigDTO:
        participant = next((p for p in self.participants
                            if p.role == FederatedParticipantType.AGGREGATOR), None)
        if participant is None:
            raise ValueError(
                "No AGGREGATOR participant in the payload; this instance cannot run the aggregator."
            )
        return participant

    def resolve_client_ids(self) -> list[str]:
        """Client ids participating in the round. In real runs the local payload only contains this
        instance's participant, so the full list must come from the relay (client_ids_override)."""
        if self.client_ids_override:
            return list(self.client_ids_override)
        return [p.participant_id for p in self.participants
                if p.role == FederatedParticipantType.CLIENT]


class FLNetLocalThreadResultDTO(FLNetBaseDTO):
    participant_id: str
    success: bool = True
    result: Any = None
    error: Optional[str] = None

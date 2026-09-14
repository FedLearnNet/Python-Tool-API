"""DTOs for relay server and orchestration controller communication.

These models represent the request/response shapes for the setup phase of a
federated learning run — creating a run on the relay and registering participants
with the orchestration controller before data communication begins.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateFLRunRequestDTO(BaseModel):
    """Request body for POST /create-fl-run on the relay server."""
    model_config = ConfigDict(populate_by_name=True)

    max_num_clients: int = Field(alias="maxNumClients")
    app_version: str = Field(default="v2", alias="appVersion")


class CreateFLRunResponseDTO(BaseModel):
    """Response from POST /create-fl-run on the relay server."""
    model_config = ConfigDict(populate_by_name=True)

    channel: str
    relay_key: str = Field(alias="relayKey")
    coordinator_id: str = Field(alias="coordinatorId")
    coordinator_key: str = Field(alias="coordinatorKey")
    client_ids: list[str] = Field(alias="clientIds")
    client_id_to_client_key: dict[str, str] = Field(alias="clientId2ClientKey")
    max_num_clients: Optional[int] = Field(default=None, alias="maxNumClients")


class StartLearningRequestDTO(BaseModel):
    """Request body for POST /start-learning on the orchestration controller.

    appKey is chosen by the caller — we control it; the controller routes
    FL communication for this participant using it. In dockerized simulation
    mode the participant_id is used as appKey (unique, convenient).
    """
    model_config = ConfigDict(populate_by_name=True)

    channel: str
    client_id: str = Field(alias="clientId")
    client_key: str = Field(alias="clientKey")
    relay_key: str = Field(alias="relayKey")
    run_id: str = Field(alias="runId")
    coordinator_id: str = Field(alias="coordinatorId")
    max_num_clients: int = Field(alias="maxNumClients")
    order_client_ids: list[str] = Field(alias="orderClientIds")
    app_key: str = Field(alias="appKey")
    app_version: str = Field(default="v2", alias="appVersion")


class StartLearningResponseDTO(BaseModel):
    """Response from POST /start-learning (200 OK; no payload expected)."""
    model_config = ConfigDict(populate_by_name=True)


class StopLearningRequestDTO(BaseModel):
    """Request body for POST /stop-learning on the orchestration controller."""
    model_config = ConfigDict(populate_by_name=True)

    channel: str
    client_id: str = Field(alias="clientId")

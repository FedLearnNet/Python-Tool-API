"""Status reporter that forwards federated run events to the backend via WebSocket.

Used by the frontend-triggered runner to publish:
- FederatedTestRunCreateDTO updates (status / currentRound)
- FederatedParticipantUpdateDTO per participant
- FederatedRoundMessageCreateDTO per send/receive

Every method is best-effort: if no ws_client is attached the calls become no-ops,
which keeps the reporter usable in pure-local tests.
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from pyfedappwrap.engine.service.socket.messages.federated import (
    FederatedParticipantUpdateDTO,
    FederatedRoundMessageCreateDTO,
    FederatedTestRunCreateDTO,
    SendFederatedFinishRunDTO,
    SendFederatedParticipantUpdateDTO,
    SendFederatedRoundMessageDTO,
    SendFederatedUpdateRunDTO,
)


class FederatedStatusReporter:
    def __init__(self, ws_client: Optional[Any], federated_run_id: int):
        self.ws_client = ws_client
        self.federated_run_id = federated_run_id
        self._lock = threading.Lock()
        # per-participant counters kept locally so the runner doesn't have to
        self._messages_sent: dict[str, int] = {}
        self._messages_received: dict[str, int] = {}

    # ----- run level ---------------------------------------------------------

    def update_run(self, status: str, current_round: Optional[int] = None,
                   error: Optional[str] = None,
                   output_data: Optional[dict[str, Any]] = None) -> None:
        if self.ws_client is None:
            return
        dto = FederatedTestRunCreateDTO(
            id=self.federated_run_id,
            status=status,
            current_round=current_round,
            error=error,
            output_data=output_data,
        )
        self.ws_client.send(SendFederatedUpdateRunDTO(message=dto))

    def finish_run(self, status: str = "FINISHED", current_round: Optional[int] = None,
                   error: Optional[str] = None,
                   output_data: Optional[dict[str, Any]] = None) -> None:
        if self.ws_client is None:
            return
        dto = FederatedTestRunCreateDTO(
            id=self.federated_run_id,
            status=status,
            current_round=current_round,
            error=error,
            output_data=output_data,
        )
        self.ws_client.send(SendFederatedFinishRunDTO(message=dto))

    # ----- participant level -------------------------------------------------

    def update_participant(self, participant_id: str, *, status: Optional[str] = None,
                           current_round: Optional[int] = None,
                           waiting_for: Optional[list[str]] = None) -> None:
        if self.ws_client is None:
            return
        with self._lock:
            sent = self._messages_sent.get(participant_id, 0)
            received = self._messages_received.get(participant_id, 0)
        dto = FederatedParticipantUpdateDTO(
            federated_run_id=self.federated_run_id,
            participant_id=participant_id,
            status=status,
            current_round=current_round,
            messages_sent=sent,
            messages_received=received,
            waiting_for=waiting_for,
        )
        self.ws_client.send(SendFederatedParticipantUpdateDTO(message=dto))

    # ----- round messages ----------------------------------------------------

    def round_message(self, *, receive: bool = False, send: bool = False, round_nr: Optional[int],
                      from_participant: str, to_participant: str,
                      communication_id: Optional[str], payload_preview: Optional[str]) -> None:
        # Always bump local counters so update_participant reflects the truth.
        if not send and not receive:
            raise ValueError("At least one of send or receive must be True")
        if send and receive:
            raise ValueError("Only one of send or receive can be True")
        with self._lock:
            if send:
                self._messages_sent[from_participant] = self._messages_sent.get(from_participant,
                                                                                0) + 1
            if receive:
                self._messages_received[to_participant] = self._messages_received.get(
                    to_participant, 0) + 1

        if self.ws_client is None:
            print(
                "WARNING: FederatedStatusReporter.round_message called but no ws_client attached, skipping report")
            return
        dto = FederatedRoundMessageCreateDTO(
            federated_run_id=self.federated_run_id,
            direction="RECEIVE" if receive else "SEND" if send else "UNKNOWN",
            round=round_nr,
            from_participant=from_participant,
            to_participant=to_participant,
            communication_id=communication_id,
            payload_preview=payload_preview,
        )
        self.ws_client.send(SendFederatedRoundMessageDTO(message=dto))

    def get_counts(self, participant_id: str) -> tuple[int, int]:
        with self._lock:
            return (
                self._messages_sent.get(participant_id, 0),
                self._messages_received.get(participant_id, 0),
            )

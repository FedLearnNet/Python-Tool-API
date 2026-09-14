from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Optional
from datetime import datetime
import json

import requests

from pyfedappwrap.engine.enums.test_embed_states import RunType
from pyfedappwrap.engine.observer.subject import Subject
from pyfedappwrap.engine.federated.models import (
    FLNetDataNoticeDTO,
    FLNetDataPackageDTO,
    FLNetLocalTestConfigDTO,
    FLNetSendDataToAggregatorMetadataDTO,
    FLNetSendDataToClientsMetadataDTO,
    FLNetReceiveDataFromAggregatorRequestDTO,
    FLNetReceiveDataFromClientsRequestDTO,
    FLNetMessageMetaDTO,
)
from pyfedappwrap.engine.config.defaults import AUTO_COMM_ID
from pyfedappwrap.engine.service.socket.messages.app import SendFederatedDataNoticeDTO


class _MockResponse:
    def __init__(self, status_code: int, payload: Any = None):
        self.status_code = status_code
        self._payload = payload
        self.content = b"" if payload is None else b"payload"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FLNetInMemoryController:
    def __init__(self, config: FLNetLocalTestConfigDTO):
        self.config = config
        self._lock = threading.Lock()
        self._queues: dict[str, list[FLNetDataPackageDTO]] = defaultdict(list)
        self._auto_round_by_sender: dict[str, int] = defaultdict(int)
        self.notice_subject = Subject()

    def send_data_to_aggregator(self, sender_id: str, request_dto: FLNetSendDataToAggregatorMetadataDTO, data: bytes) -> dict:
        communication_id = self._resolve_communication_id(
            sender_id,
            request_dto.communication_id,
        )
        package = FLNetDataPackageDTO(
            data=json.loads(data),
            meta=FLNetMessageMetaDTO(
                communicationId=communication_id,
                fromClientId=sender_id,
                toAggregator=request_dto.to_aggregator,
                timeArrived=datetime.now(),
            )
        )
        recipient = self.config.aggregator_id
        pending_notices = []
        with self._lock:
            self._queues[recipient].append(package.model_copy(deep=True))
            pending_notices.append(
                SendFederatedDataNoticeDTO(
                    message=FLNetDataNoticeDTO(
                        recipient_id=recipient,
                        sender_id=sender_id,
                        communication_id=communication_id,
                    ),
                    run_type=RunType.FEDERATED_RUN,
                )
            )
        for notice in pending_notices:
            self.notice_subject.set_state(notice)
        return {"communicationId": communication_id}

    def send_data_to_clients(self, sender_id: str, request_dto: FLNetSendDataToClientsMetadataDTO, data: bytes) -> dict:
        package = FLNetDataPackageDTO(
            data=json.loads(data),
            meta=FLNetMessageMetaDTO(
                communicationId=request_dto.communication_id,
                fromClientId=sender_id,
                fromAggregator=request_dto.from_aggregator,
                timeArrived=datetime.now(),
            )
        )
        recipients = request_dto.to
        if not recipients:
            # If 'to' is empty and from_aggregator is set, broadcast to all clients
            recipients = [p.participant_id for p in self.config.participants if p.participant_id != sender_id and p.participant_id != self.config.aggregator_id]

        pending_notices = []
        with self._lock:
            for recipient in recipients:
                self._queues[recipient].append(package.model_copy(deep=True))
                pending_notices.append(
                    SendFederatedDataNoticeDTO(
                        message=FLNetDataNoticeDTO(
                            recipient_id=recipient,
                            sender_id=sender_id,
                            communication_id=request_dto.communication_id,
                        ),
                        run_type=RunType.FEDERATED_RUN,
                    )
                )
        for notice in pending_notices:
            self.notice_subject.set_state(notice)
        return {"communicationId": request_dto.communication_id}

    def receive_data_from_aggregator(self, receiver_id: str, request_dto: FLNetReceiveDataFromAggregatorRequestDTO) -> tuple[int, Optional[dict]]:
        with self._lock:
            queue = self._queues[receiver_id]
            packages = [p for p in queue if p.meta.from_aggregator == request_dto.from_aggregator]
            if request_dto.communication_id:
                packages = [p for p in packages if p.meta.communication_id == request_dto.communication_id]
            else:
                # get newest automatic comm id
                if not packages:
                    return 204, None
                last_seen_index = {p.meta.communication_id: i for i, p in enumerate(packages)}
                newest_id = max(last_seen_index, key=last_seen_index.get)
                packages = [p for p in packages if p.meta.communication_id == newest_id]

            if not packages:
                return 204, None

            selected = packages[0]
            queue.remove(selected)
            return 200, {
                "data": selected.data,
                "meta": selected.meta.model_dump(by_alias=True, exclude_none=True)
            }

    def receive_data_from_clients(self, receiver_id: str, request_dto: FLNetReceiveDataFromClientsRequestDTO) -> tuple[int, Optional[dict]]:
        with self._lock:
            queue = self._queues[receiver_id]
            packages = queue
            if request_dto.from_client_ids:
                packages = [p for p in packages if p.meta.sender in request_dto.from_client_ids]
            if request_dto.to_aggregator:
                packages = [p for p in packages if p.meta.to_aggregator == request_dto.to_aggregator]
            if request_dto.communication_id:
                packages = [p for p in packages if p.meta.communication_id == request_dto.communication_id]

            grouped_packages = defaultdict(list)
            for package in packages:
                grouped_packages[package.meta.communication_id].append(package)

            selected_packages = None
            for group in grouped_packages.values():
                if len(group) >= request_dto.min_packages:
                    selected_packages = group[:request_dto.min_packages]
                    break

            if selected_packages is None:
                return 204, None

            for p in selected_packages:
                queue.remove(p)

            # group by comm id
            grouped = defaultdict(list)
            for p in selected_packages:
                grouped[p.meta.communication_id].append({
                    "data": p.data,
                    "meta": p.meta.model_dump(by_alias=True, exclude_none=True)
                })

            return 200, dict(grouped)

    def _resolve_communication_id(self, sender_id: str,
                                  communication_id: str | None) -> str:
        if communication_id != AUTO_COMM_ID:
            return communication_id or AUTO_COMM_ID
        self._auto_round_by_sender[sender_id] += 1
        return f"{AUTO_COMM_ID}_{self._auto_round_by_sender[sender_id]}"

    def build_session(self, participant_id: str) -> "FLNetInMemoryControllerSession":
        return FLNetInMemoryControllerSession(self, participant_id)


class FLNetInMemoryControllerSession:
    def __init__(self, controller: FLNetInMemoryController, participant_id: str):
        self.controller = controller
        self.participant_id = participant_id

    def post(self, url: str, json: dict[str, Any] = None, files: dict = None, timeout: float = None, **kwargs):
        if url.endswith("/send-data-to-aggregator") and files:
            import json as json_mod
            metadata = json_mod.loads(files["metadata"][1])
            data = files["data"][1]
            req_dto = FLNetSendDataToAggregatorMetadataDTO.model_validate(metadata)
            res = self.controller.send_data_to_aggregator(self.participant_id, req_dto, data)
            return _MockResponse(200, res)

        if url.endswith("/send-data-to-clients") and files:
            import json as json_mod
            metadata = json_mod.loads(files["metadata"][1])
            data = files["data"][1]
            req_dto = FLNetSendDataToClientsMetadataDTO.model_validate(metadata)
            res = self.controller.send_data_to_clients(self.participant_id, req_dto, data)
            return _MockResponse(200, res)

        if url.endswith("/receive-data-from-aggregator"):
            req_dto = FLNetReceiveDataFromAggregatorRequestDTO.model_validate(json)
            status_code, payload = self.controller.receive_data_from_aggregator(self.participant_id, req_dto)
            return _MockResponse(status_code, payload)

        if url.endswith("/receive-data-from-clients"):
            req_dto = FLNetReceiveDataFromClientsRequestDTO.model_validate(json)
            status_code, payload = self.controller.receive_data_from_clients(self.participant_id, req_dto)
            return _MockResponse(status_code, payload)

        return _MockResponse(404, {"error": f"Unsupported URL: {url}"})

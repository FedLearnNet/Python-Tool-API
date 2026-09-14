from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional, List

import requests

from pyfedappwrap.engine.config.defaults import DEFAULT_APP_COMM_TIMEOUT, AUTO_COMM_ID
from pyfedappwrap.engine.federated.reporter import FederatedStatusReporter
from pyfedappwrap.engine.config.system_config import FLNetDPSettings, FLNetSMPCSettings, \
    system_settings
from pyfedappwrap.engine.enums.test_embed_states import TestEmbedEnum
from pyfedappwrap.engine.federated.errors import FLNetCommunicationError
from pyfedappwrap.engine.federated.models import (
    FLNetDataNoticeDTO,
    FLNetDataPackageDTO,
    FLNetReceiveDataFromAggregatorRequestDTO,
    FLNetReceiveDataFromClientsRequestDTO,
    FLNetReceiveSetupResponseDTO,
    FLNetSendDataToClientsMetadataDTO,
    FLNetSendDataToAggregatorMetadataDTO,
    FLNetMessageMetaDTO,
)
from pyfedappwrap.engine.federated.serializer import FLNetSerializer
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage

logger = logging.getLogger(__name__)


class _FederatedNoticeObserver:
    def __init__(self, communicator: "FLNetCommunicator", subject):
        self.communicator = communicator
        self.subject = subject
        self.subject.register(self)

    def update(self, state):
        self.communicator.handle_notice_event(state)


class FLNetCommunicator:
    def __init__(self,
                 controller_url: str,
                 app_key: str,
                 controller_app_key: str,
                 client_id: str,
                 client_ids: List[str],
                 aggregator_id: str,
                 channel: str,
                 *,
                 session=None,
                 serializer: Optional[FLNetSerializer] = None,
                 timeout: float = DEFAULT_APP_COMM_TIMEOUT,
                 poll_interval: float = 1.0,
                 max_polls: int = 60):
        self.controller_url = controller_url.rstrip("/")
        self.app_key = app_key
        # Key used in FL controller HTTP requests (appKey field).
        # Distinct from app_key, which is the WebSocket auth token.
        self.controller_app_key = controller_app_key
        self.channel = channel
        self.client_id = client_id
        self.client_ids = client_ids
        self.aggregator_id = aggregator_id
        self.session = session or requests.Session()
        self.serializer = serializer or FLNetSerializer()
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self._auto_communication_counter = 0
        self._notice_condition = threading.Condition()
        self._pending_notices: list[FLNetDataNoticeDTO] = []
        self._notice_observer: Optional[_FederatedNoticeObserver] = None
        self._status_reporter = None
        self._reporter_participant_id: Optional[str] = None

    @property
    def _effective_controller_app_key(self) -> str:
        """The appKey to use in FL controller HTTP requests."""
        return self.controller_app_key

    @property
    def is_aggregator(self) -> bool:
        return self.client_id == self.aggregator_id

    @property
    def auto_counter(self) -> int:
        return self._auto_communication_counter

    def attach_status_reporter(self, reporter: FederatedStatusReporter, participant_id: str):
        self._status_reporter = reporter
        self._reporter_participant_id = participant_id

    def receive_setup(self) -> FLNetReceiveSetupResponseDTO:
        """Request setup information from the controller."""
        payload = {
            "appKey": self._effective_controller_app_key,
            "channel": self.channel,
        }
        response = self._post("/receive-setup", payload)
        response_payload = self._read_json(response)
        return FLNetReceiveSetupResponseDTO.model_validate(response_payload or {})

    def bind_notice_subject(self, subject):
        if subject is None:
            return
        if self._notice_observer is not None:
            if self._notice_observer.subject is subject:
                return
            self.unbind_notice_subject()
        self._notice_observer = _FederatedNoticeObserver(self, subject)

    def unbind_notice_subject(self):
        observer = self._notice_observer
        if observer is None:
            return
        self._notice_observer = None
        try:
            observer.subject.unregister(observer)
        except Exception:
            pass
        with self._notice_condition:
            self._pending_notices.clear()

    def handle_notice_event(self, event: Any):
        if not isinstance(event, BaseSocketMessage):
            return
        if not TestEmbedEnum.FEDERATED_DATA_NOTICE.equals(event.type):
            return

        message = event.message
        notice = (
            message
            if isinstance(message, FLNetDataNoticeDTO)
            else FLNetDataNoticeDTO.model_validate(message)
        )
        if notice.recipient_id != self._resolve_notice_recipient_id():
            return

        with self._notice_condition:
            self._pending_notices.append(notice)
            self._notice_condition.notify_all()

    # ── Private send helpers ──────────────────────────────────────────────────

    def _send_to_aggregator(self,
                            data: Any,
                            *,
                            communication_id: Optional[str],
                            aggregator_name: str,
                            smpc: Optional[FLNetSMPCSettings],
                            dp: Optional[FLNetDPSettings]) -> str:
        """
        Helper method that sends data to the aggregator with the given communication_id and settings.
        Only to be used by a client!
        """
        # Validation
        if self.is_aggregator:
            raise ValueError(
                "Aggregator: Cannot send data to another aggreagtor or myself as an aggregator"
            )
        smpc = self._resolve_smpc_settings(smpc)
        dp = self._resolve_dp_settings(dp)
        if not communication_id:
            communication_id = AUTO_COMM_ID

        # create files to send
            # data
        data_bytes = json.dumps(self.serializer.serialize(data)).encode("utf-8")
        # metadata
        metadata = FLNetSendDataToAggregatorMetadataDTO(
            appKey=self._effective_controller_app_key,
            channel=self.channel,
            serializationUsed="json",
            communicationId=communication_id,
            toAggregator=aggregator_name,
            smpc=smpc,
            dp=dp,
        ).model_dump(by_alias=True, exclude_none=True)

        # Send the message
        files = {
            "metadata": (None, json.dumps(metadata), "application/json"),
            "data": ("payload.bin", data_bytes, "application/octet-stream"),
        }
        response = self._post_multipart("/send-data-to-aggregator", files)
        response_payload = self._read_json(response)
        round_nr = self._report_send_event_from_client(
            send_to_aggregator=True,
            send_to_clients=False,
            recipients=None,
            aggregator_name=aggregator_name,
            communication_id=communication_id or AUTO_COMM_ID,
            data=data,
        )
        controller_communication_id = (
            response_payload.get("communicationId")
            or response_payload.get("communication_id")
        )
        if controller_communication_id:
            return controller_communication_id
        if communication_id == AUTO_COMM_ID and round_nr is not None:
            return f"{AUTO_COMM_ID}_{round_nr}"
        return communication_id

    def _send_to_clients_p2p(self,
                         data: Any,
                         *,
                         communication_id: str,
                         to: List[str],
                         dp: Optional[FLNetDPSettings]) -> str:
        """
        Helper method to send data to clients with the given communication_id and settings.
        Can be used by clients for peer to peer communication,
        but also by the aggregator to broadcast to clients.
        """
        data_bytes = json.dumps(self.serializer.serialize(data)).encode("utf-8")
        if self.aggregator_id in to:
            raise ValueError(
                f"Cannot send a peer-to-peer message to the aggregator/coordinator "
                f"({self.aggregator_id!r}). Use send_data_to_aggregator instead."
            )
        dp = self._resolve_dp_settings(dp)
        metadata = FLNetSendDataToClientsMetadataDTO(
            appKey=self._effective_controller_app_key,
            channel=self.channel,
            serializationUsed="json",
            communicationId=communication_id,
            to=to,
            dp=dp,
        ).model_dump(by_alias=True, exclude_none=True)
        files = {
            "metadata": (None, json.dumps(metadata), "application/json"),
            "data": ("payload.bin", data_bytes, "application/octet-stream"),
        }
        self._post_multipart("/send-data-to-clients", files)
        self._report_send_event_from_client(
            send_to_aggregator=False,
            send_to_clients=True,
            recipients=to,
            aggregator_name=None,
            communication_id=communication_id,
            data=data,
        )

        return communication_id

    def _send_to_clients_broadcast(self,
                         data: Any,
                         *,
                         communication_id: str,
                         from_aggregator: str,
                         to: Optional[List[str]] = None,
                         dp: Optional[FLNetDPSettings] = None) -> str:
        """Helper method to broadcast data to clients with the given communication_id and settings.
        Only to be used by the aggregator, as it sends to all clients when `to` is None."""
        if not self.is_aggregator:
            raise ValueError(
                "Only the aggregator can broadcast data to clients. Use _send_to_clients_p2p instead."
            )
        data_bytes = json.dumps(self.serializer.serialize(data)).encode("utf-8")
        dp = self._resolve_dp_settings(dp)
        metadata = FLNetSendDataToClientsMetadataDTO(
            appKey=self._effective_controller_app_key,
            channel=self.channel,
            serializationUsed="json",
            to=to,
            fromAggregator=from_aggregator,
            communicationId=communication_id,
            dp=dp
        ).model_dump(by_alias=True, exclude_none=True)
        files = {
            "metadata": (None, json.dumps(metadata), "application/json"),
            "data": ("payload.bin", data_bytes, "application/octet-stream"),
        }
        self._post_multipart("/send-data-to-clients", files)
        self._report_send_event_from_aggregator(
            recipients=to,
            communication_id=communication_id,
            aggregator_name=from_aggregator,
            data=data,
        )
        return communication_id

    # ── Private receive helpers ───────────────────────────────────────────────

    def _receive_from_aggregator_package(self,
                                          aggregator_name: str,
                                          communication_id: Optional[str] = None,
                                          data_type: Any = None) -> Optional[FLNetDataPackageDTO]:
        payload = FLNetReceiveDataFromAggregatorRequestDTO(
            appKey=self._effective_controller_app_key,
            channel=self.channel,
            serializationFormat="json",
            fromAggregator=aggregator_name,
            communicationId=communication_id,
        ).model_dump(by_alias=True, exclude_none=True)

        response = self._post("/receive-data-from-aggregator", payload, allow_no_content=True)

        if response.status_code == 204:
            # No available data yet
            return None
        elif response.status_code == 404:
            # controller doesnt know the learning yet, treat as no data
            return None
        elif response.status_code == 409:
            # Learning was stopped
            raise TimeoutError(f"Learning was stopped while waiting for data from aggregator {aggregator_name!r}.")
        elif response.status_code == 410:
            # Run failed with an error
            raise FLNetCommunicationError(f"Learning run failed with an error while waiting for data from aggregator {aggregator_name!r}.")
        elif response.status_code != 200:
            raise FLNetCommunicationError(f"Unexpected response status code {response.status_code} while waiting for data from aggregator {aggregator_name!r}.")

        raw = self._read_json(response)
        if not raw:
            raise FLNetCommunicationError(f"Failed to read JSON response while waiting for data from aggregator {aggregator_name!r}.")
        package = self._parse_received_package(payload= raw, data_type=data_type)
        self._report_receive_events([package])
        return package

    def _receive_from_clients_grouped(self,
                                      min_packages_per_round: int,
                                      from_clients: Optional[List[str]],
                                      to_aggregator: Optional[str],
                                      communication_id: Optional[str] = None,
                                      data_type: Any = None) -> dict[str, list[FLNetDataPackageDTO]]:
        payload = FLNetReceiveDataFromClientsRequestDTO(
            appKey=self._effective_controller_app_key,
            channel=self.channel,
            serializationFormat="json",
            toAggregator=to_aggregator,
            communicationId=communication_id,
            fromClientIds=from_clients or [],
            minPackages=min_packages_per_round,
        ).model_dump(by_alias=True, exclude_none=True)

        response = self._post("/receive-data-from-clients", payload)
        raw_grouped = self._read_json(response)
        if not raw_grouped or not isinstance(raw_grouped, dict):
            return {}

        result: dict[str, list[FLNetDataPackageDTO]] = {}
        for comm_id, messages in raw_grouped.items():
            result[comm_id] = []
            for message in messages:
                package = self._parse_received_package(payload=message, data_type=data_type)
                result[comm_id].append(package)
            self._report_receive_events([package for package in result[comm_id]])

        return result

    def _wait_before_next_receive(
            self,
            *,
            poll_count: int,
            communication_id: Optional[str],
            from_clients: Optional[list[str]],
            deadline: float) -> bool:
        if poll_count >= self.max_polls:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        wait_timeout = min(self.poll_interval, remaining)
        if wait_timeout <= 0:
            return True
        return self._wait_for_notice(
            communication_id=communication_id,
            from_clients=from_clients,
            timeout=wait_timeout,
        ) or time.monotonic() < deadline

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _parse_received_package(self,
                                payload: Any,
                                data_type: Any = None) -> FLNetDataPackageDTO:
        if isinstance(payload, list):
            payload = payload[0]
        meta_data = payload.get("meta", {})
        if not meta_data:
            raise FLNetCommunicationError("Received data package without meta information.")
        meta_data = self.serializer.deserialize(meta_data)
        data = payload.get("data", None)
        if data is None:
            raise FLNetCommunicationError("Received data package without data.")
        return FLNetDataPackageDTO(
            meta=FLNetMessageMetaDTO.model_validate(meta_data),
            data=self.serializer.deserialize(data, data_type),
        )

    def _wait_for_notice(self,
                         *,
                         communication_id: Optional[str],
                         from_clients: Optional[list[str]],
                         timeout: float) -> bool:
        with self._notice_condition:
            if self._consume_matching_notice(communication_id, from_clients):
                return True

            end_time = time.monotonic() + timeout
            while True:
                remaining = end_time - time.monotonic()
                if remaining <= 0:
                    return False
                self._notice_condition.wait(timeout=remaining)
                if self._consume_matching_notice(communication_id, from_clients):
                    return True

    def _consume_matching_notice(self,
                                 communication_id: Optional[str],
                                 from_clients: Optional[list[str]]) -> bool:
        matched = False
        remaining: list[FLNetDataNoticeDTO] = []
        for notice in self._pending_notices:
            if communication_id is not None and notice.communication_id != communication_id:
                remaining.append(notice)
                continue
            if from_clients is not None and notice.sender_id not in from_clients:
                remaining.append(notice)
                continue
            matched = True
        self._pending_notices = remaining
        return matched

    def attach_traffic_logger(self, traffic_logger):
        """Attach a callable(path, bytes_sent, bytes_received, status_code) invoked after every
        controller HTTP call, so the platform can persist controller traffic as run log messages."""
        self._traffic_logger = traffic_logger

    def _emit_traffic(self, path: str, bytes_sent: int, bytes_received: int, status_code: int):
        # HTTP 204 = empty poll (no data yet). These fire continuously while a round waits, so log them
        # at debug only — at info they flood the container logs. Calls that carried data still log at info.
        if status_code == 204:
            logger.debug("[CONTROLLER] POST %s sent=%dB received=%dB status=%d (empty poll)",
                         path, bytes_sent, bytes_received, status_code)
        else:
            logger.info("[CONTROLLER] POST %s sent=%dB received=%dB status=%d",
                        path, bytes_sent, bytes_received, status_code)
        traffic_logger = getattr(self, "_traffic_logger", None)
        if traffic_logger is not None:
            try:
                traffic_logger(path, bytes_sent, bytes_received, status_code)
            except Exception:
                logger.debug("Traffic logger failed for %s", path, exc_info=True)

    @staticmethod
    def _multipart_size(files: dict) -> int:
        total = 0
        for part in files.values():
            body = part[1] if isinstance(part, tuple) and len(part) > 1 else part
            if hasattr(body, "getbuffer"):
                total += body.getbuffer().nbytes
            elif isinstance(body, (bytes, bytearray)):
                total += len(body)
            elif isinstance(body, str):
                total += len(body.encode("utf-8"))
        return total

    def _post(self, path: str, payload: dict[str, Any], *,
              allow_no_content: bool = False):
        bytes_sent = len(json.dumps(payload).encode("utf-8"))
        response = self.session.post(
            f"{self.controller_url}{path}",
            json=payload,
            timeout=self.timeout,
        )
        self._emit_traffic(path, bytes_sent, len(response.content or b""), response.status_code)
        if allow_no_content and response.status_code == 204:
            return response
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise FLNetCommunicationError(f"Controller call to {path} failed: {exc}") from exc
        return response

    def _post_multipart(self, path: str, files: dict):
        bytes_sent = self._multipart_size(files)
        response = self.session.post(
            f"{self.controller_url}{path}",
            files=files,
            timeout=self.timeout,
        )
        self._emit_traffic(path, bytes_sent, len(response.content or b""), response.status_code)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise FLNetCommunicationError(f"Controller call to {path} failed: {exc}") from exc
        return response

    def _read_json(self, response) -> dict[str, Any] | list[Any]:
        if not getattr(response, "content", b""):
            return {}
        payload = response.json()
        if payload is None:
            return {}
        return payload

    def _resolve_notice_recipient_id(self) -> str:
        return self.client_id

    def _report_send_event_from_client(self,
                            *,
                            send_to_aggregator: bool = False,
                            send_to_clients: bool = False,
                            recipients: Optional[List[str]],
                            aggregator_name: Optional[str],
                            communication_id: str,
                            data: Any) -> Optional[int]:
        if self._status_reporter is None:
            logger.warning("No status reporter attached, cannot report send events")
            return
        if send_to_aggregator and send_to_clients:
            logger.warning("Internal error: should never report both send_to_aggregator and send_to_clients at the same time")
            return

        # We can only report rounds for the clients -> aggregator communication
        # that uses the automatic comm ID that counts rounds
        round_nr = None
        if not send_to_clients and (not communication_id or communication_id == AUTO_COMM_ID):
            self._auto_communication_counter += 1
            round_nr = self._auto_communication_counter
            communication_id = AUTO_COMM_ID

        if recipients is None or len(recipients) == 0 or recipients == [self.aggregator_id]:
            if send_to_clients:
                raise ValueError("Recipients must be provided when reporting send_to_clients events")
            recipients = [self._parse_aggregator_string_to_report(self.aggregator_id, aggregator_name)]

        payload_preview = str(self.serializer.serialize(data))[:100]
        for recipient in recipients:
            self._status_reporter.round_message(
                receive=False,
                send=True,
                round_nr=round_nr,
                from_participant=self.client_id,
                to_participant=recipient,
                communication_id=communication_id,
                payload_preview=payload_preview,
            )
        return round_nr

    def _report_send_event_from_aggregator(self,
                                           *,
                                           recipients: Optional[List[str]],
                                           communication_id: str,
                                           aggregator_name: str,
                                           data: Any) -> None:
        if self._status_reporter is None:
            logger.warning("No status reporter attached, cannot report send events")
            return
        payload_preview = str(self.serializer.serialize(data))[:100]
        if not self.is_aggregator:
            raise ValueError("Only the aggregator can report send events from aggregator")
        if recipients is None or len(recipients) == 0:
            recipients = [f"{client_id} (client)" for client_id in self.client_ids]
        for recipient in recipients:
            self._status_reporter.round_message(
                receive=False,
                send=True,
                round_nr=None,
                from_participant=self._parse_aggregator_string_to_report(self.aggregator_id, aggregator_name),
                to_participant=recipient,
                communication_id=communication_id,
                payload_preview=payload_preview,
            )

    def _report_receive_events(self, packages: list[FLNetDataPackageDTO]) -> None:
        if self._status_reporter is None:
            return
        recipient = self._reporter_participant_id or self._resolve_notice_recipient_id()
        for package in packages:
            round_nr = None
            if package.meta.communication_id.startswith(AUTO_COMM_ID):
                try:
                    round_nr = int(package.meta.communication_id[len(AUTO_COMM_ID):])
                except (IndexError, ValueError):
                    round_nr = None
            payload_preview = str(self.serializer.serialize(package.data))[:100]
            self._status_reporter.round_message(
                receive=True,
                send=False,
                round_nr=round_nr,
                from_participant=package.meta.sender,
                to_participant=recipient,
                communication_id=package.meta.communication_id,
                payload_preview=payload_preview,
            )

    @staticmethod
    def _resolve_smpc_settings(
            smpc: Optional[FLNetSMPCSettings]) -> Optional[FLNetSMPCSettings]:
        """
        Normalizes SMPC settings by applying the following precedence:
        1. If `smpc` is provided as an argument and enabled, use it.
        2. Else, if SMPC is enabled in the global system settings, use those settings.
        3. Otherwise, return None to indicate that SMPC is not enabled.
        All clients must enable SMPC via system settings or the communication breaks
        with a timeout.
        """
        if smpc is not None:
            return smpc
        if system_settings.smpc.enabled:
            return FLNetSMPCSettings(
                useSmpc=system_settings.smpc.use_smpc,
                exponent=system_settings.smpc.exponent,
                numShards=system_settings.smpc.num_shards,
                operation=system_settings.smpc.operation,
            )
        return None

    @staticmethod
    def _resolve_dp_settings(
            dp: Optional[FLNetDPSettings]) -> Optional[FLNetDPSettings]:
        """
        Normalizes DP settings by applying the following precedence:
        1. If `dp` is provided as an argument and enabled, use it.
        2. Else, if DP is enabled in the global system settings, use those settings.
        3. Otherwise, return None to indicate that DP is not enabled.
        """
        if dp is not None and dp.enabled:
            return dp
        if system_settings.dp.enabled:
            return FLNetDPSettings(
                enabled=system_settings.dp.enabled,
                epsilon=system_settings.dp.epsilon,
                delta=system_settings.dp.delta,
                sensitivity=system_settings.dp.sensitivity,
                clippingVal=system_settings.dp.clipping_val,
                noisetype=system_settings.dp.noise_type,
            )
        return None

    @staticmethod
    def _parse_aggregator_string_to_report(aggregator_id: str, aggregator_name: Optional[str]) -> str:
        return f"{aggregator_id} (aggregator:{aggregator_name})" if aggregator_name else f"{aggregator_id} (aggregator:unknown)"

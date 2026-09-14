"""Client for setting up dockerized federated test runs."""
from __future__ import annotations

import logging
import requests as http_requests

from requests import Response

from pyfedappwrap.engine.config.system_config import system_settings, FLTestSettings
from pyfedappwrap.engine.federated.models import (
    FederatedParticipantType,
    FLNetLocalParticipantConfigDTO,
    FLNetLocalTestConfigDTO,
)
from pyfedappwrap.engine.federated.orchestration import (
    CreateFLRunRequestDTO,
    CreateFLRunResponseDTO,
    StartLearningRequestDTO,
)
from pyfedappwrap.engine.service.socket.messages.federated import (
    FederatedTestRunCreateDTO,
)
from pyfedappwrap.engine.tests.federated.dockerized_services import (
    ensure_dockerized_federated_services,
)


logger = logging.getLogger(__name__)


class FederatedDockerizedControllerClient:
    HEALTH_CHECK_TIMEOUT_SECONDS = 3
    REQUEST_TIMEOUT_SECONDS = 20

    def __init__(self):
        self.config: FLTestSettings = system_settings.fl_test

    def setup_dockerized_fl_run(
            self,
            run_dto: FederatedTestRunCreateDTO,
            config: FLNetLocalTestConfigDTO,
            participants: list[FLNetLocalParticipantConfigDTO],
    ) -> None:
        """Register all participants with the relay and orchestration controller.

        Sets ``config.channel`` in-place.
        Raises ``requests.HTTPError`` if any setup request fails.
        """
        relay_url = self._normalize_url(self.config.dockerized_relay_url)
        controller_orch_url = self._normalize_url(self.config.dockerized_controller_orch_url)
        controller_comm_url = self._normalize_url(self.config.dockerized_controller_comm_url)

        logger.info(
            "Setting up dockerized federated test run id=%s relay=%s controller_orch=%s controller_comm=%s",
            run_dto.id,
            relay_url,
            controller_orch_url,
            controller_comm_url,
        )
        ensure_dockerized_federated_services(
            relay_url=relay_url,
            controller_orch_url=controller_orch_url,
            startup_timeout_seconds=90.0,
            health_timeout_seconds=self.HEALTH_CHECK_TIMEOUT_SECONDS,
        )
        self._assert_service_healthy("relay", relay_url)
        self._assert_service_healthy("orchestration controller", controller_orch_url)
        config.use_external_controller = True
        config.controller_url = controller_comm_url
        logger.info("Dockerized federated test run will use external controller at %s", controller_comm_url)

        client_participants = [p for p in participants if p.role == FederatedParticipantType.CLIENT]
        aggregator_participant = next(
            (p for p in participants if p.role == FederatedParticipantType.AGGREGATOR), None
        )
        n_clients = len(client_participants)
        if n_clients == 0:
            raise ValueError("At least one federated client participant is required.")

        run_info = self._create_relay_run(relay_url, n_clients)
        config.channel = run_info.channel
        logger.info(
            "Created dockerized federated relay run channel=%s coordinator=%s clients=%s",
            run_info.channel,
            run_info.coordinator_id,
            run_info.client_ids,
        )

        relay_client_ids = run_info.client_ids
        if len(relay_client_ids) != n_clients:
            raise RuntimeError(
                f"Relay returned {len(relay_client_ids)} client IDs for {n_clients} configured clients."
            )

        for i, participant in enumerate(client_participants):
            relay_client_id = relay_client_ids[i]
            relay_client_key = run_info.client_id_to_client_key[relay_client_id]
            start_learning_req = self._build_start_learning_request(
                run_id=str(run_dto.id),
                channel=run_info.channel,
                client_id=relay_client_id,
                client_key=relay_client_key,
                relay_key=run_info.relay_key,
                coordinator_id=run_info.coordinator_id,
                max_num_clients=n_clients,
                ordered_client_ids=relay_client_ids,
                app_key=participant.participant_id,
            )
            self._start_learning(controller_orch_url, start_learning_req)
            logger.info(
                "Registered dockerized federated client participant=%s relay_client_id=%s",
                participant.participant_id,
                relay_client_id,
            )

        if aggregator_participant is not None:
            start_learning_req = self._build_start_learning_request(
                run_id=str(run_dto.id),
                channel=run_info.channel,
                client_id=run_info.coordinator_id,
                client_key=run_info.coordinator_key,
                relay_key=run_info.relay_key,
                coordinator_id=run_info.coordinator_id,
                max_num_clients=n_clients,
                ordered_client_ids=relay_client_ids,
                app_key=aggregator_participant.participant_id,
            )
            self._start_learning(controller_orch_url, start_learning_req)
            logger.info(
                "Registered dockerized federated aggregator participant=%s coordinator_id=%s",
                aggregator_participant.participant_id,
                run_info.coordinator_id,
            )


    @staticmethod
    def _normalize_url(url: str) -> str:
        normalized_url = url.rstrip("/")
        if not normalized_url:
            raise ValueError("Federated service URL must not be empty.")
        return normalized_url

    def _assert_service_healthy(self, label: str, base_url: str) -> None:
        response = self._request(
            method="get",
            url=f"{base_url}/healthz",
            timeout=self.HEALTH_CHECK_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Federated {label} at {base_url!r} returned HTTP {response.status_code}. "
                "Make sure the docker-compose services are running."
            )

    def _create_relay_run(self, relay_url: str, n_clients: int) -> CreateFLRunResponseDTO:
        create_request = CreateFLRunRequestDTO.model_validate({"maxNumClients": n_clients})
        response = self._request(
            method="post",
            url=f"{relay_url}/create-fl-run",
            json=create_request.model_dump(by_alias=True),
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return CreateFLRunResponseDTO.model_validate(response.json())

    @staticmethod
    def _build_start_learning_request(
            *,
            run_id: str,
            channel: str,
            client_id: str,
            client_key: str,
            relay_key: str,
            coordinator_id: str,
            max_num_clients: int,
            ordered_client_ids: list[str],
            app_key: str,
    ) -> StartLearningRequestDTO:
        return StartLearningRequestDTO.model_validate({
            "channel": channel,
            "clientId": client_id,
            "clientKey": client_key,
            "relayKey": relay_key,
            "runId": run_id,
            "coordinatorId": coordinator_id,
            "maxNumClients": max_num_clients,
            "orderClientIds": ordered_client_ids,
            "appKey": app_key,
        })

    def _start_learning(
            self,
            controller_orch_url: str,
            start_learning_request: StartLearningRequestDTO,
    ) -> None:
        response = self._request(
            method="post",
            url=f"{controller_orch_url}/start-learning",
            json=start_learning_request.model_dump(by_alias=True),
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    @staticmethod
    def _request(method: str, url: str, **kwargs) -> Response:
        try:
            return http_requests.request(method=method, url=url, **kwargs)
        except http_requests.RequestException as exc:
            raise RuntimeError(
                f"Federated service request to {url!r} failed: {exc}. "
                "Make sure the docker-compose services are running."
            ) from exc

"""Worker manager for frontend-triggered federated test runs."""
from __future__ import annotations

import copy
import logging
import shutil
import threading
from pathlib import Path
from typing import Any, Optional

from pyfedappwrap.engine.config.defaults import DEFAULT_APP_COMM_TIMEOUT
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.federated.aggregator import AppAggregator
from pyfedappwrap.engine.enums.test_embed_states import RunType, TestEmbedEnum
from pyfedappwrap.engine.federated.models import (
    FederatedParticipantType,
    FLNetLocalParticipantConfigDTO,
    FLNetLocalTestConfigDTO,
)
from pyfedappwrap.engine.federated.reporter import FederatedStatusReporter
from pyfedappwrap.engine.federated.serializer import FLNetSerializer
from pyfedappwrap.engine.logger import WebSocketLogger
from pyfedappwrap.engine.observer.observer import Observer
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.service.socket.messages.federated import (
    FederatedParticipantConfigDTO,
    FederatedTestRunCreateDTO,
)
from pyfedappwrap.engine.tests.federated.controller_client import \
    FederatedDockerizedControllerClient
from pyfedappwrap.engine.tests.federated.runner import LocalFederatedRunner


class FederatedWorkerManager(Observer):
    """Observes the WebSocket client for federated run start events."""

    def __init__(self, ws_client, lifecycle, upload_client=None):
        super().__init__("FederatedWorkerManager", ws_client)
        self.ws_client = ws_client
        self.lifecycle = lifecycle
        self.upload_client = upload_client
        self.available_app: Optional[Any] = None
        self._aggregators: dict[str, AppAggregator] = {}
        self._active_runs: dict[int, threading.Thread] = {}
        self._lock = threading.Lock()
        self._serializer = FLNetSerializer()

    def register_aggregator(self, aggregator: AppAggregator, key: str = "default") -> None:
        self._aggregators[key] = aggregator

    def set_aggregators(self, aggregators: dict[str, AppAggregator]) -> None:
        self._aggregators = dict(aggregators)

    def get_aggregator(self, key: str = "default") -> Optional[AppAggregator]:
        return self._aggregators.get(key)

    def update(self, event: BaseSocketMessage):
        if event is None:
            return
        event_type = getattr(event, "type", None)
        if event_type is None:
            return
        if not (
            TestEmbedEnum.START_FEDERATED_RUN.equals(event_type)
            or TestEmbedEnum.START_FEDERATED_TEST_RUN.equals(event_type)
        ):
            return

        message = getattr(event, "message", None)
        if message is None:
            logging.warning("Federated start event received without message payload")
            return

        # Some callers use START_FEDERATED_RUN plus runType=FEDERATED_TEST_RUN,
        # while local simulation helpers may emit START_FEDERATED_TEST_RUN.
        run_type = self._effective_run_type(event_type, getattr(event, "run_type", None))
        try:
            self._handle_start(message, run_type=run_type)
        except Exception as exc:
            logging.exception("Failed to start federated run: %s", exc)

    def _handle_start(self, message: Any, *, run_type: Any) -> None:
        if isinstance(message, FederatedTestRunCreateDTO):
            run_dto = message
        elif isinstance(message, dict):
            run_dto = FederatedTestRunCreateDTO.model_validate(message)
        elif hasattr(message, "model_dump"):
            run_dto = FederatedTestRunCreateDTO.model_validate(message.model_dump(by_alias=True))
        else:
            logging.warning("Unexpected federated start payload type: %s", type(message))
            return

        with self._lock:
            if run_dto.id in self._active_runs and self._active_runs[run_dto.id].is_alive():
                logging.info("Federated run %s already running, ignoring duplicate", run_dto.id)
                return

        thread = threading.Thread(
            target=self._run_federated,
            name=f"fed-run-{run_dto.id}",
            args=(run_dto, run_type),
            daemon=True,
        )
        with self._lock:
            self._active_runs[run_dto.id] = thread
        thread.start()

    @staticmethod
    def _build_participants(
            participants: Optional[list[FederatedParticipantConfigDTO]],
            total_rounds: Optional[int] = None,
    ) -> list[FLNetLocalParticipantConfigDTO]:
        if not participants:
            return []
        result: list[FLNetLocalParticipantConfigDTO] = []
        for p in participants:
            base_dir = (p.config.base_dir if p.config and p.config.base_dir
                        else f"/tmp/fedrun/{p.participant_id}")
            data_dir = p.config.data_dir if p.config else None
            output_dir = p.config.output_dir if p.config else None
            hyper_params = dict(p.hyper_params or {})
            if total_rounds is not None:
                hyper_params.setdefault("federated_rounds", total_rounds)
            result.append(FLNetLocalParticipantConfigDTO(
                participant_id=p.participant_id,
                role=p.role,
                base_dir=Path(base_dir),
                data_dir=Path(data_dir) if data_dir else None,
                output_dir=Path(output_dir) if output_dir else None,
                hyper_params=hyper_params,
                input_file_paths=p.input_file_paths or {},
            ))
        return result

    @staticmethod
    def _is_test_run(run_type: Any) -> bool:
        return RunType.FEDERATED_TEST_RUN.equals(run_type)

    @classmethod
    def _effective_run_type(cls, event_type: Any, run_type: Any) -> Any:
        if cls._is_test_run(run_type) or TestEmbedEnum.START_FEDERATED_TEST_RUN.equals(event_type):
            return RunType.FEDERATED_TEST_RUN
        return run_type

    @classmethod
    def _should_use_external_controller(cls, run_type: Any) -> bool:
        if cls._is_test_run(run_type):
            return system_settings.fl_test.use_dockerized_controller
        return True

    @staticmethod
    def _resolve_controller_url(
            *,
            run_type: Any,
            use_external_controller: bool,
    ) -> Optional[str]:
        if not use_external_controller:
            return None
        if FederatedWorkerManager._is_test_run(run_type):
            source = "FL_TEST__DOCKERIZED_CONTROLLER_COMM_URL"
            configured_url = system_settings.fl_test.dockerized_controller_comm_url
        else:
            source = "FL_RUN__CONTROLLER_COMM_URL"
            configured_url = system_settings.fl_run.controller_comm_url
        resolved_url = (configured_url or "").strip().rstrip("/")
        if not resolved_url:
            raise ValueError(f"External federated runs require a controller URL. Set {source}.")
        logging.info("Federated controller URL resolved: source=%s url=%s", source, resolved_url)
        return resolved_url

    def _stage_input_files(self, participant: FLNetLocalParticipantConfigDTO) -> None:
        if not participant.input_file_paths:
            return

        data_dir = participant.data_dir or (participant.base_dir / "data")
        data_dir.mkdir(parents=True, exist_ok=True)
        source_root = Path(system_settings.data_dir)

        for relative_path in participant.input_file_paths.values():
            source = source_root / relative_path
            if not source.exists():
                logging.warning("Skipping missing federated input file %s for %s", source, participant.participant_id)
                continue

            target = data_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    @staticmethod
    def _build_run_config(
            run_dto: FederatedTestRunCreateDTO,
            participants: list[FLNetLocalParticipantConfigDTO],
            *,
            run_type: Any,
    ) -> FLNetLocalTestConfigDTO:
        cfg = run_dto.config
        use_external_controller = FederatedWorkerManager._should_use_external_controller(run_type)
        coordinator_id = getattr(cfg, "coordinator_id", None) if cfg else None
        client_ids_override = None
        order_client_ids = getattr(cfg, "order_client_ids", None) if cfg else None
        if order_client_ids:
            # The relay's client list; exclude the coordinator defensively in case the backend
            # includes it (the coordinator occupies the separate aggregator slot).
            client_ids_override = [
                client_id for client_id in order_client_ids if client_id != coordinator_id
            ]
        # Real distributed rounds (clinics train + network + the coordinator's own contribution) need a
        # far more generous wait than the in-memory test path: 500 polls * 0.01s = 5s times out a real
        # round. Use ~600s (0.25s * 2400) for real runs unless the backend overrides it.
        is_test = FederatedWorkerManager._is_test_run(run_type)
        default_poll_interval = 0.01 if is_test else 0.25
        default_timeout = DEFAULT_APP_COMM_TIMEOUT if is_test else 600.0
        default_max_polls = 500 if is_test else 2400
        config = FLNetLocalTestConfigDTO(
            participants=participants,
            poll_interval=cfg.poll_interval if cfg and cfg.poll_interval else default_poll_interval,
            timeout=cfg.timeout if cfg and cfg.timeout else default_timeout,
            max_polls=cfg.max_polls if cfg and cfg.max_polls else default_max_polls,
            start_aggregator=run_dto.start_aggregator if run_dto.start_aggregator is not None else True,
            channel=cfg.channel if cfg and cfg.channel else "local-test",
            use_external_controller=use_external_controller,
            controller_url=FederatedWorkerManager._resolve_controller_url(
                run_type=run_type,
                use_external_controller=use_external_controller,
            ),
            simulate_participants_locally=FederatedWorkerManager._is_test_run(run_type),
            aggregator_id_override=coordinator_id,
            client_ids_override=client_ids_override,
        )
        logging.info(
            "Built federated run config run_type=%s use_dockerized_controller=%s "
            "use_external_controller=%s controller_url=%s simulate_participants_locally=%s channel=%s",
            run_type,
            system_settings.fl_test.use_dockerized_controller,
            config.use_external_controller,
            config.controller_url,
            config.simulate_participants_locally,
            config.channel,
        )
        return config

    def _run_federated(self, run_dto: FederatedTestRunCreateDTO, run_type: Any) -> None:
        run_id = run_dto.id
        reporter = FederatedStatusReporter(self.ws_client, run_id)
        reporter.update_run(status="STARTED", current_round=0)

        try:
            if self.available_app is None:
                reporter.finish_run(status="ERROR", error="No federated app registered")
                return

            participants = self._build_participants(
                run_dto.participants,
                total_rounds=run_dto.total_rounds,
            )
            if not participants:
                reporter.finish_run(status="ERROR", error="No participants configured")
                return

            if not self._is_test_run(run_type):
                # Real runs: results must land in OUTPUT_DIR (the platform's output volume) so the
                # learning API can harvest them after FINISH. Without this, participants (notably
                # the aggregator) write to /tmp/fedrun/<id>/output inside the container and the
                # results are lost when the container is cleaned up.
                for participant in participants:
                    if participant.output_dir is None:
                        participant.output_dir = Path(system_settings.output_dir)

            config = self._build_run_config(run_dto, participants, run_type=run_type)

            if (
                self._is_test_run(run_type)
                and system_settings.fl_test.use_dockerized_controller
            ):
                logging.info(
                    "Federated test run %s uses dockerized controller; starting/checking services before runner.",
                    run_id,
                )
                test_manger = FederatedDockerizedControllerClient()
                test_manger.setup_dockerized_fl_run(run_dto, config, participants)
                logging.info(
                    "Federated test run %s dockerized setup complete: controller_url=%s channel=%s",
                    run_id,
                    config.controller_url,
                    config.channel,
                )
            else:
                logging.info(
                    "Federated run %s uses %s controller path.",
                    run_id,
                    "in-memory" if not config.use_external_controller else "configured external",
                )

            apps_by_participant: dict[str, Any] = {}
            for participant in participants:
                self._stage_input_files(participant)
                # Clients train; the coordinator (AGGREGATOR) also trains on its own data in addition
                # to running the aggregator, so it gets a training app too (the runner bridges its
                # local update into the aggregation in-process).
                if participant.role in (FederatedParticipantType.CLIENT, FederatedParticipantType.AGGREGATOR):
                    app = copy.deepcopy(self.available_app)
                    app.logger = WebSocketLogger(
                        f"FederatedParticipant[{participant.participant_id}]",
                        self.ws_client,
                        run_id,
                        RunType.FEDERATED_RUN,
                        process_name=participant.participant_id,
                        worker_id=participant.participant_id,
                    )
                    if hasattr(app, "set_status_reporter"):
                        app.set_status_reporter(reporter)
                    apps_by_participant[participant.participant_id] = app
                reporter.update_participant(
                    participant.participant_id,
                    status="INITIALIZED",
                    current_round=0,
                )

            reporter.update_run(status="RUNNING", current_round=0)

            runner = LocalFederatedRunner(
                config,
                aggregators=self._aggregators,
                ws_client=self.ws_client,
                upload_client=getattr(self, "upload_client", None),
                lifecycle=self.lifecycle,
                reporter=reporter,
                run_id=run_id,
                run_type=RunType.FEDERATED_RUN,
            )
            results = runner.run(apps_by_participant)

            any_error: Optional[str] = None
            aggregator_output: Optional[dict[str, Any]] = None
            client_output: Optional[dict[str, Any]] = None
            for participant in participants:
                outcome = results.get(participant.participant_id)
                if outcome is None:
                    continue
                reporter.update_participant(
                    participant.participant_id,
                    status="FINISHED" if outcome.success else "ERROR",
                )
                if participant.participant_id == config.aggregator_id and outcome.success and outcome.result is not None:
                    aggregator_output = {
                        "aggregator_aggregatorId": participant.participant_id,
                        "aggregator_result": self._serializer.serialize(outcome.result),
                    }
                elif (
                    client_output is None
                    and participant.role == FederatedParticipantType.CLIENT
                    and outcome.success
                    and outcome.result is not None
                ):
                    client_output = {
                        "clientId": participant.participant_id,
                        "result": self._serializer.serialize(outcome.result),
                    }
                if not outcome.success and any_error is None:
                    any_error = outcome.error

            if any_error is not None:
                reporter.finish_run(status="ERROR", error=any_error, output_data=aggregator_output)
            else:
                reporter.finish_run(status="FINISHED", output_data=aggregator_output)

            if client_output is not None and self.upload_client is not None:
                combined = {**(aggregator_output or {}), **client_output}
                try:
                    self.upload_client.upload_output(
                        RunType.FEDERATED_RUN, run_id, combined
                    )
                except Exception as upload_exc:
                    logging.warning(
                        "Federated run %s: HTTP output upload failed: %s",
                        run_id, upload_exc,
                    )

        except Exception as exc:
            logging.exception("Federated run %s crashed: %s", run_id, exc)
            reporter.finish_run(status="ERROR", error=f"{type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                self._active_runs.pop(run_id, None)

"""Worker manager for frontend-triggered federated test runs."""
from __future__ import annotations

import copy
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from pyfedappwrap.engine.config.defaults import DEFAULT_APP_COMM_TIMEOUT
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.federated.aggregator import AppAggregator
from pyfedappwrap.engine.enums.test_embed_states import RunType, WebsocketMessageTypes
from pyfedappwrap.engine.federated.models import (
    FederatedParticipantType,
    FLNetLocalParticipantConfigDTO,
    FLNetLocalTestConfigDTO,
)
from pyfedappwrap.engine.federated.reporter import FederatedStatusReporter
from pyfedappwrap.engine.federated.serializer import FLNetSerializer
from pyfedappwrap.engine.logger import WebSocketLogger
from pyfedappwrap.engine.observer.observer import Observer
from pyfedappwrap.engine.service.flower import certs as flower_certs
from pyfedappwrap.engine.service.flower.cli import FlowerCliError
from pyfedappwrap.engine.service.flower.lifecycle import FlowerRunLifecycle
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.service.socket.messages.federated import (
    FederatedParticipantConfigDTO,
    FederatedTestRunCreateDTO,
    FlowerSupernodeKeyDTO,
    FlowerSupernodeRegisteredDTO,
    SendFlowerSupernodeKeyDTO,
    SendFlowerSupernodeRegisteredDTO,
)
from pyfedappwrap.engine.tests.federated.controller_client import \
    FederatedDockerizedControllerClient
from pyfedappwrap.engine.tests.federated.runner import LocalFederatedRunner
from pyfedappwrap.learning.federated.flower_app import FlowerApp


# A clinic re-sends its SuperNode public key this often until the platform's aggregator confirms
# the registration - the aggregator's SuperLink may not be up yet, and nothing on the way
# (local, global) keeps the request - and gives up after the timeout.
SUPERNODE_REGISTRATION_RETRY_SECONDS = 10.0
SUPERNODE_REGISTRATION_TIMEOUT_SECONDS = 600.0


class FederatedWorkerManager(Observer):
    """Observes the WebSocket client for federated run start events."""

    def __init__(self, ws_client, lifecycle, upload_client=None):
        super().__init__("FederatedWorkerManager", ws_client)
        self.ws_client = ws_client
        self.lifecycle = lifecycle
        self.upload_client = upload_client
        self.available_app: Optional[Any] = None
        self.available_flower_app: Optional[FlowerApp] = None
        self._aggregators: dict[str, AppAggregator] = {}
        self._active_runs: dict[int, threading.Thread] = {}
        self._flower_lifecycles: dict[int, FlowerRunLifecycle] = {}
        # Aggregator container: the lifecycle running this run's SuperLink, which registers the
        # clinics' SuperNode keys. Clinic container: its own registration requests in flight.
        self._flower_aggregator: Optional[FlowerRunLifecycle] = None
        self._pending_registrations: dict[str, tuple[threading.Event, list]] = {}
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
        if WebsocketMessageTypes.FLOWER_SUPERNODE_KEY.equals(event_type):
            self._on_supernode_key(getattr(event, "message", None))
            return
        if WebsocketMessageTypes.FLOWER_SUPERNODE_REGISTERED.equals(event_type):
            self._on_supernode_registered(getattr(event, "message", None))
            return
        if not (
                WebsocketMessageTypes.START_FEDERATED_RUN.equals(event_type)
                or WebsocketMessageTypes.START_FEDERATED_TEST_RUN.equals(event_type)
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
        if hasattr(message, "model_dump"):
            message = message.model_dump(by_alias=True)
        if not isinstance(message, dict):
            logging.warning("Unexpected federated start payload type: %s", type(message))
            return
        upload_client = self.upload_client.for_execution(message) if self.upload_client else None
        run_dto = FederatedTestRunCreateDTO.model_validate(message)

        with self._lock:
            if run_dto.id in self._active_runs and self._active_runs[run_dto.id].is_alive():
                logging.info("Federated run %s already running, ignoring duplicate", run_dto.id)
                return

        # Same message, same entry point either way - just a different method per engine:
        # an if/else on the communication engine, not a separate message type
        if run_dto.communication_engine == "FLOWER":
            target, args = self._start_federated_run_flower, (run_dto, run_type, upload_client)
        else:
            target, args = self._start_federated_run_flnet, (run_dto, run_type, upload_client)

        thread = threading.Thread(
            target=target,
            name=f"fed-run-{run_dto.id}",
            args=args,
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
        if cls._is_test_run(run_type) or WebsocketMessageTypes.START_FEDERATED_TEST_RUN.equals(event_type):
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
            distributed_test: bool = False,
    ) -> Optional[str]:
        if not use_external_controller:
            return None
        if FederatedWorkerManager._is_test_run(run_type) and not distributed_test:
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
            if relative_path.startswith(("http://", "https://")):
                continue
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
        use_external_controller = run_dto.distributed_test or FederatedWorkerManager._should_use_external_controller(run_type)
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
        is_test = FederatedWorkerManager._is_test_run(run_type) and not run_dto.distributed_test
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
                distributed_test=run_dto.distributed_test,
            ),
            simulate_participants_locally=is_test,
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

    def _discard_flower_lifecycle(self, run_id: int) -> None:
        with self._lock:
            self._flower_lifecycles.pop(run_id, None)

    def _start_federated_run_flower(self, run_dto: FederatedTestRunCreateDTO, run_type: Any,
                                    upload_client=None) -> None:
        upload_client = upload_client or self.upload_client
        run_id = run_dto.id
        reporter = FederatedStatusReporter(self.ws_client, run_id, run_type=RunType.FEDERATED_RUN)
        reporter.update_run(status="STARTED", current_round=0)
        try:
            if self.available_flower_app is None:
                reporter.finish_run(status="ERROR", error="No Flower app registered")
                return
            if len(run_dto.participants) != 1:
                reporter.finish_run(
                    status="ERROR",
                    error=f"A Flower run expects exactly one participant per container, got {len(run_dto.participants)}",
                )
                return

            participant = run_dto.participants[0]
            lifecycle = FlowerRunLifecycle(self.available_flower_app)
            with self._lock:
                self._flower_lifecycles[run_id] = lifecycle

            if participant.role == FederatedParticipantType.AGGREGATOR.value:
                cert_dir = Path(f"/tmp/fedrun/{run_id}/certs")
                leaf_hostnames = ["0.0.0.0", "127.0.0.1"]
                cfg = run_dto.config
                own_address = cfg.superlink_address if cfg else None
                if own_address:
                    # host[:port] -> the leaf cert's SAN must cover whatever hostname/IP a
                    # clinic's SuperNode actually dials, or TLS hostname verification fails even
                    # with the right CA - loopback alone (above) is not enough.
                    leaf_hostnames.append(own_address.rsplit(":", 1)[0])
                # The SuperLink only runs TLS with the stored CA this run's clinics were also
                # given; a newly generated CA is reported up for later runs (see certs.py).
                tls = flower_certs.prepare_superlink_tls(
                    cert_dir, leaf_hostnames,
                    ca_cert_pem=cfg.ca_certificate if cfg else None,
                    ca_key_pem=cfg.ca_private_key if cfg else None,
                )
                if tls.ca_to_report:
                    reporter.report_ca_certificate(*tls.ca_to_report)
                # Blocks this thread until the run finishes - same shape as FL-Net's own
                # _start_federated_run_flnet below - so the lifecycle is done by the time we get
                # here and can be discarded.
                with self._lock:
                    self._flower_aggregator = lifecycle
                try:
                    success, error = lifecycle.run_as_aggregator(
                        ssl_certfile=tls.files.leaf_cert_path if tls.files else None,
                        ssl_keyfile=tls.files.leaf_key_path if tls.files else None,
                        ssl_ca_certfile=tls.files.ca_cert_path if tls.files else None,
                        report_running=lambda: reporter.update_run(status="RUNNING"),
                    )
                finally:
                    with self._lock:
                        self._flower_aggregator = None
                self._discard_flower_lifecycle(run_id)
                if success:
                    error = self._upload_flower_model(lifecycle, upload_client, run_id)
                    success = error is None
                reporter.finish_run(status="FINISHED" if success else "ERROR", error=error)
            else:
                cfg = run_dto.config
                if not cfg or not cfg.superlink_address:
                    self._discard_flower_lifecycle(run_id)
                    reporter.finish_run(
                        status="ERROR",
                        error="No SuperLink address provisioned for this Flower client (see "
                              "FederatedRunConfigDTO.superlink_address)",
                    )
                    return
                root_certificates = None
                if cfg.ca_certificate:
                    root_certificates = flower_certs.write_ca_certificate(
                        Path(f"/tmp/fedrun/{run_id}/certs"), cfg.ca_certificate)
                elif cfg.superlink_root_certificates_path:
                    root_certificates = Path(cfg.superlink_root_certificates_path)
                auth_private_key = (Path(cfg.supernode_auth_private_key_path)
                                    if cfg.supernode_auth_private_key_path else None)
                if root_certificates is not None and auth_private_key is None:
                    # With TLS the platform's SuperLink only admits registered SuperNodes
                    # (--enable-supernode-auth); without it (first run) there's nothing to do.
                    auth_private_key, error = self._register_supernode(run_id)
                    if auth_private_key is None:
                        self._discard_flower_lifecycle(run_id)
                        reporter.finish_run(status="ERROR", error=error)
                        return
                lifecycle.start_as_client(
                    superlink_address=cfg.superlink_address,
                    root_certificates=root_certificates,
                    auth_private_key=auth_private_key,
                )
                reporter.update_run(status="RUNNING")
                # Deliberately NOT discarded here: start_as_client() doesn't block, the
                # SuperNode keeps running, and this is our only handle to stop it later (when
                # the orchestrator ends this attempt, the same way every other attempt type's
                # container lifecycle already ends - see lifecycle.py's module docstring).
        except Exception as exc:
            self._discard_flower_lifecycle(run_id)
            logging.exception("Flower run %s crashed: %s", run_id, exc)
            reporter.finish_run(status="ERROR", error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _upload_flower_model(
            lifecycle: FlowerRunLifecycle, upload_client, run_id: int) -> Optional[str]:
        """Uploads the model the aggregator's ServerApp saved, as FL-Net's path does through
        ModelSaver - but a failed upload fails the run here: the platform's attempt is the step's
        selected attempt, so a run reported FINISHED without its model would leave the step
        without one. Returns an error message, or None."""
        model_path = lifecycle.saved_model_path()
        if model_path is None:
            return None
        if upload_client is None:
            logging.warning("No upload client, not uploading the Flower model %s", model_path)
            return None
        try:
            upload_client.upload_model_file(
                run_id=run_id, name=model_path.name, file_path=str(model_path))
        except Exception as exc:  # noqa: BLE001 - any failure means the model didn't arrive
            logging.exception("Uploading the Flower model %s failed", model_path)
            return f"Uploading the model {model_path.name} failed: {type(exc).__name__}: {exc}"
        logging.info("Uploaded the Flower model %s for run %s", model_path, run_id)
        return None

    def _register_supernode(self, run_id: int) -> tuple[Optional[Path], Optional[str]]:
        """Clinic: generates this SuperNode's auth keypair and has the platform's aggregator
        register its public key, re-sending until confirmed. Returns (private key path, None), or
        (None, error) when the aggregator refuses it or never answers in time."""
        keypair = flower_certs.generate_supernode_keypair(Path(f"/tmp/fedrun/{run_id}/supernode"))
        request_id = str(uuid.uuid4())
        answered = threading.Event()
        answer: list[FlowerSupernodeRegisteredDTO] = []
        with self._lock:
            self._pending_registrations[request_id] = (answered, answer)
        deadline = time.monotonic() + SUPERNODE_REGISTRATION_TIMEOUT_SECONDS
        last_error = "the platform's aggregator did not answer"
        try:
            while time.monotonic() < deadline:
                self.ws_client.send(SendFlowerSupernodeKeyDTO(message=FlowerSupernodeKeyDTO(
                    request_id=request_id, public_key=keypair.public_key)))
                if answered.wait(SUPERNODE_REGISTRATION_RETRY_SECONDS):
                    if answer[0].success:
                        logging.info("SuperNode of run %s is registered with the platform", run_id)
                        return keypair.private_key_path, None
                    # Usually "SuperLink not running yet" - wait for the next round.
                    last_error = answer[0].error or "registration refused"
                    logging.info("SuperNode registration of run %s not done yet: %s",
                                 run_id, last_error)
                    answered.clear()
                    answer.clear()
                    time.sleep(SUPERNODE_REGISTRATION_RETRY_SECONDS)
        finally:
            with self._lock:
                self._pending_registrations.pop(request_id, None)
        return None, (f"SuperNode was not registered with the platform within "
                      f"{SUPERNODE_REGISTRATION_TIMEOUT_SECONDS:.0f}s: {last_error}")

    def _on_supernode_registered(self, message: Any) -> None:
        """Clinic: the aggregator's answer to one of our registration requests."""
        try:
            answer = FlowerSupernodeRegisteredDTO.model_validate(
                message.model_dump(by_alias=True) if hasattr(message, "model_dump") else message)
        except ValueError:
            logging.warning("Ignoring malformed SuperNode registration answer")
            return
        with self._lock:
            pending = self._pending_registrations.get(answer.request_id)
        if pending is None:
            return
        answered, answers = pending
        answers[:] = [answer]
        answered.set()

    def _on_supernode_key(self, message: Any) -> None:
        """Aggregator: registers a clinic's SuperNode key with this run's SuperLink and answers.
        Runs off the websocket thread - the `flwr` call can take a few seconds."""
        try:
            request = FlowerSupernodeKeyDTO.model_validate(
                message.model_dump(by_alias=True) if hasattr(message, "model_dump") else message)
        except ValueError:
            logging.warning("Ignoring malformed SuperNode registration request")
            return
        threading.Thread(target=self._register_supernode_key, args=(request,),
                         name=f"flower-register-{request.request_id}", daemon=True).start()

    def _register_supernode_key(self, request: FlowerSupernodeKeyDTO) -> None:
        with self._lock:
            lifecycle = self._flower_aggregator
        try:
            if lifecycle is None:
                raise FlowerCliError("No Flower aggregator is running in this container")
            lifecycle.register_supernode(request.public_key, name=request.name)
            answer = FlowerSupernodeRegisteredDTO(request_id=request.request_id, success=True)
        except FlowerCliError as exc:
            answer = FlowerSupernodeRegisteredDTO(request_id=request.request_id, success=False,
                                                  error=str(exc))
        self.ws_client.send(SendFlowerSupernodeRegisteredDTO(message=answer))

    def _start_federated_run_flnet(self, run_dto: FederatedTestRunCreateDTO, run_type: Any, upload_client=None) -> None:
        upload_client = upload_client or self.upload_client
        run_id = run_dto.id
        execution_type = RunType.FEDERATED_TEST_RUN if self._is_test_run(run_type) else RunType.FEDERATED_RUN
        reporter = FederatedStatusReporter(self.ws_client, run_id, run_type=execution_type)
        reporter.update_run(status="STARTED", current_round=0)
        test_manager = None

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

            if not self._is_test_run(run_type) or run_dto.distributed_test:
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
                and not run_dto.distributed_test
                and system_settings.fl_test.use_dockerized_controller
            ):
                logging.info(
                    "Federated test run %s uses dockerized controller; starting/checking services before runner.",
                    run_id,
                )
                test_manager = FederatedDockerizedControllerClient()
                test_manager.setup_dockerized_fl_run(run_dto, config, participants)
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
                # local update into the aggregation in-process). An aggregator-only run (e.g. the
                # platform as aggregator, which holds no data) gets no training app, so the runner
                # only runs the aggregation loop for it.
                aggregator_only = (run_dto.aggregator_only is True
                                   and participant.role == FederatedParticipantType.AGGREGATOR)
                if (participant.role in (FederatedParticipantType.CLIENT, FederatedParticipantType.AGGREGATOR)
                        and not aggregator_only):
                    app = copy.deepcopy(self.available_app)
                    app.logger = WebSocketLogger(
                        f"FederatedParticipant[{participant.participant_id}]",
                        self.ws_client,
                        run_id,
                        execution_type,
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
                upload_client=upload_client,
                lifecycle=self.lifecycle,
                reporter=reporter,
                run_id=run_id,
                run_type=execution_type,
                round_source_app=self.available_app,
            )
            results = runner.run(apps_by_participant)
            if test_manager is not None:
                test_manager.cleanup()

            aggregator_output: Optional[dict[str, Any]] = None
            outcome = results.get(config.aggregator_id)
            if outcome is not None and outcome.success and outcome.result is not None:
                aggregator_output = {
                    "aggregator_aggregatorId": config.aggregator_id,
                    "aggregator_result": self._serializer.serialize(outcome.result),
                }
                if upload_client is not None:
                    upload_client.upload_output(run_type, run_id, aggregator_output)

            any_error: Optional[str] = None
            for participant in participants:
                outcome = results.get(participant.participant_id)
                if outcome is None:
                    continue
                reporter.update_participant(
                    participant.participant_id,
                    status="FINISHED" if outcome.success else "ERROR",
                )
                if not outcome.success and any_error is None:
                    any_error = outcome.error

            if any_error is not None:
                reporter.finish_run(status="ERROR", error=any_error, output_data=aggregator_output)
            else:
                reporter.finish_run(status="FINISHED", output_data=aggregator_output)

        except Exception as exc:
            if test_manager is not None:
                test_manager.cleanup()
            logging.exception("Federated run %s crashed: %s", run_id, exc)
            reporter.finish_run(status="ERROR", error=f"{type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                self._active_runs.pop(run_id, None)

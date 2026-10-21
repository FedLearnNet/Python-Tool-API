"""Engine-internal worker for a pure aggregator-only participant (no local data).

Not part of the public app-developer API. ``WorkerManager`` instantiates this instead of the
app developer's own registered ``BaseFederatedApp``/``BaseApp`` when a ``START_RUN`` task's
role is AGGREGATOR and carries no input data at all (the platform-as-aggregator case) - see
``WorkerManager._resolve_aggregator_only`` for the detection logic.

Drives the same round loop ``LocalFederatedRunner._run_aggregator`` already runs correctly for
local test simulations (``await_data_from_clients`` -> registered ``AppAggregator.aggregate()``
-> ``broadcast``), but against a real ``FLNetCommunicatorAggregator`` built from the real task
body, so apps need zero code changes to support this role - the engine handles it transparently.
"""
from __future__ import annotations

import asyncio
import threading
import time
import traceback
from asyncio import Queue
from typing import Optional

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import RunType, WebsocketMessageTypes
from pyfedappwrap.engine.federated.aggregator import AppAggregator
from pyfedappwrap.engine.logger import WebSocketLogger
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.controller.aggregator import FLNetCommunicatorAggregator
from pyfedappwrap.engine.service.socket.messages.app import AppTaskMessage, SendUpdateRunDTO
from pyfedappwrap.engine.worker.run_dto import RunStatusTypes, UpdateTestRunDTO


def extract_round_count(body: dict) -> int:
    """Resolves how many rounds to run, preferring the pre-computed top-level field Learning
    APIs already sends (``StartRunDTO.totalRounds``) over re-deriving it from hyperParams."""
    total_rounds = body.get("totalRounds")
    if total_rounds:
        return int(total_rounds)
    hyper_params = body.get("hyperParams") or {}
    value = hyper_params.get("federated_rounds", hyper_params.get("total_rounds"))
    if value:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return 1


class AggregatorOnlyWorker:
    """Minimal stand-in for ``BaseApp`` implementing just the surface ``WorkerManager`` drives
    a worker through, so it can be scheduled exactly like a normal app's worker thread."""

    def __init__(self, aggregators: dict[str, AppAggregator]):
        self._aggregators = aggregators
        self.status = RunStatusTypes.INITIALIZED
        self.finish_event: Optional[threading.Event] = None
        self.task_queue: Optional[Queue] = None
        self.websocket_client = None
        self.run_id = None
        self.run_type = RunType.NOT_DEFINED
        self._lifecycle: Optional[EngineLifecycle] = None
        self.stop_worker = None
        self.logger = None

    def set_startup(self, websocket_client, upload_client, app_id, run_id, run_type: RunType,
                    lifecycle: EngineLifecycle, stop_worker):
        self.websocket_client = websocket_client
        self.run_id = run_id
        self.run_type = run_type
        self._lifecycle = lifecycle
        self.stop_worker = stop_worker
        self.logger = WebSocketLogger(
            f"AggregatorOnlyWorker {app_id}", self.websocket_client, self.run_id, self.run_type,
            worker_id=app_id,
        )
        self.task_queue = Queue()
        self.finish_event = threading.Event()

    def get_status(self):
        return self.status

    def stop(self, error=None):
        self.finish_event.set()

    async def enqueue_task(self, task: AppTaskMessage):
        await self.task_queue.put(task)

    def update_status(self, status: RunStatusTypes, error: str = None):
        self.status = status
        if self.logger is not None:
            self.logger.info(f"Status updated: {status}")
        dto = UpdateTestRunDTO(run_id=self.run_id, status=status, error=error)
        self.websocket_client.send(SendUpdateRunDTO(message=dto, run_type=self.run_type))

    def start_app(self):
        asyncio.run(self._start_process())

    async def _start_process(self):
        try:
            self.update_status(RunStatusTypes.RUNNING)
            while not self._lifecycle.is_stopping() and not self.finish_event.is_set():
                if not self.task_queue.empty():
                    task = await self.task_queue.get()
                    self._perform_task(task)
                else:
                    time.sleep(1)
            self.stop_worker()
            self.update_status(RunStatusTypes.FINISHED)
        except Exception as e:
            self.update_status(RunStatusTypes.ERROR, str(e))
            if self.logger is not None:
                self.logger.error(f"Error running aggregator-only worker: {e}")
            self.stop_worker(str(e))
            traceback.print_exc()

    def _perform_task(self, task: AppTaskMessage):
        if not (WebsocketMessageTypes.START_RUN.equals(task.task)
                or WebsocketMessageTypes.START_PREDICTION.equals(task.task)):
            return
        try:
            self._run_aggregation(task.body)
        finally:
            self.finish_event.set()

    def _build_communicator(self, body: dict) -> FLNetCommunicatorAggregator:
        config = body.get("config") or {}
        aggregator_id = config.get("coordinatorId") or config.get("clientId")
        return FLNetCommunicatorAggregator(
            system_settings.fl_run.controller_comm_url,
            system_settings.app_key,
            # The Controller run was registered (via /start-learning) with this participant's
            # relay id as its appKey, not this tool's static app_api_key - using the latter here
            # makes every FL controller HTTP request (e.g. /receive-data-from-clients) address a
            # run key the Controller never registered, which 404s as "no such run key".
            controller_app_key=aggregator_id,
            client_id=aggregator_id,
            client_ids=config.get("orderClientIds") or [],
            aggregator_id=aggregator_id,
            channel=config.get("channel"),
            aggregators=self._aggregators,
        )

    def _run_aggregation(self, body: dict) -> None:
        communicator = self._build_communicator(body)
        n_rounds = extract_round_count(body)
        n_relay_clients = len(communicator.client_ids)
        try:
            for round_nr in range(1, n_rounds + 1):
                self.logger.info(
                    f"[AGGREGATOR] round {round_nr}/{n_rounds}: awaiting {n_relay_clients} relay client package(s)"
                )
                grouped_packages = communicator.await_data_from_clients(
                    to_aggregator=None,
                    num_data_packages_per_communication_round=n_relay_clients,
                    communication_id=None,
                )
                communication_id, packages = next(iter(grouped_packages.items()))
                communication_id = packages[0].communication_id
                latest_meta = packages[-1].meta
                aggregator_key = latest_meta.to_aggregator or "default"
                aggregated = communicator.aggregate(packages, aggregator_key)
                self.logger.info(
                    f"[AGGREGATOR] round {round_nr}: aggregated {len(packages)} package(s); "
                    f"broadcasting comm_id={communication_id!r} from_aggregator={aggregator_key!r}"
                )
                communicator.broadcast(
                    communication_id,
                    aggregated,
                    from_aggregator=aggregator_key,
                )
                self.logger.info(f"[AGGREGATOR] round {round_nr} complete (comm_id={communication_id})")
        finally:
            communicator.unbind_notice_subject()

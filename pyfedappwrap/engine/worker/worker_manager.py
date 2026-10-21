import asyncio
import copy
import threading
import traceback
from uuid import uuid4

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import WebsocketMessageTypes, RunType
from pyfedappwrap.engine.federated.aggregator import AppAggregator
from pyfedappwrap.engine.logger import WebSocketLogger
from pyfedappwrap.engine.observer.observer import Observer
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.socket.messages.app import AppTaskMessage
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.service.socket.socket import WebSocketClient
from pyfedappwrap.engine.service.upload.upload_client import UploadClient
from pyfedappwrap.engine.worker.aggregator_only_worker import AggregatorOnlyWorker
from pyfedappwrap.engine.worker.run_dto import RunStatusTypes


def is_aggregator_only_task(task_body: dict) -> bool:
    """"Coordinator" (clientId == coordinatorId) is a relay-protocol role - whichever participant
    the FL run's config designates as coordinator - and is distinct from "aggregator," the
    application-level role of whoever actually runs AppAggregator.aggregate(). They normally
    coincide: a clinic picked as coordinator also trains and aggregates. This function detects
    the one case where they split: this participant was assigned the coordinator role but has no
    data to train on at all - i.e. Learning APIs registered the platform itself (not a clinic) as
    coordinator, because the platform holds no patient data, so its only job for this run is
    aggregation. Mirrors FLNetCommunicator.is_aggregator for the "am I the coordinator" check.
    A coordinator CLINIC that also trains always has real input data, so it keeps going through
    the normal registered-app path unaffected."""
    config = task_body.get("config") or {}
    client_id = config.get("clientId")
    coordinator_id = config.get("coordinatorId")
    if client_id is None or coordinator_id is None or client_id != coordinator_id:
        return False
    return not task_body.get("inputFilePaths") and not task_body.get("inputData")


class WorkerManager(Observer):
    def __init__(self, websocket_client: WebSocketClient, upload_client: UploadClient, lifecycle: EngineLifecycle):
        super().__init__("WorkerManager", websocket_client)
        self.lifecycle: EngineLifecycle = lifecycle
        self.websocket_client: WebSocketClient = websocket_client
        self.upload_client: UploadClient = upload_client
        self.logger = WebSocketLogger("WorkerManager", self.websocket_client)
        self.worker = None
        self.available_worker = None
        self._aggregators: dict[str, AppAggregator] = {}
        self.logger.info(f"WorkerManager initialized.")

    def register_aggregator(self, aggregator: AppAggregator, key: str = "default") -> None:
        self._aggregators[key] = aggregator

    def set_aggregators(self, aggregators: dict[str, AppAggregator]) -> None:
        self._aggregators = dict(aggregators)

    def start_worker(self, run_id, run_type: RunType, task_body: dict | None = None):
        if self.worker is not None:
            self.logger.error(f"Cannot start app, cause App is already running.")
            return

        if task_body is not None and is_aggregator_only_task(task_body):
            self.logger.info(f"Starting aggregator-only worker (no app registered worker needed).")
            worker = AggregatorOnlyWorker(self._aggregators)
        else:
            if self.available_worker is None:
                self.logger.error(f"No App registered.")
                return
            worker = copy.deepcopy(self.available_worker)

        uuid = f"Run: {run_id}-{uuid4().__str__()}"
        worker.set_startup(self.websocket_client, self.upload_client, uuid, run_id, run_type,
                           self.lifecycle,
                           self.stop_worker)
        self.worker = worker

        # Start the worker in a separate thread
        worker_thread = threading.Thread(target=worker.start_app, daemon=True)
        worker_thread.start()
        self.logger.info(f"App started.")

    def stop_worker(self, error=None):
        if self.lifecycle.test_mode and error is not None:
            self.lifecycle.request_exit(error)
            self.logger.error(f"Error: {error}")
            raise Exception(error)
        if self.worker is not None:
            if self.worker.finish_event.is_set():
                self.worker.stop(error)
            self.worker = None
            self.logger.info(f"App stopped.")
        else:
            self.logger.error(f"Cannot stop app. App not started.")

    def get_worker_status(self):
        if self.worker is not None:
            return self.worker.get_status()
        return "not found"

    def enqueue_task(self, task):
        if self.worker is not None:
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                loop.run_until_complete(self.worker.enqueue_task(task))
            else:
                loop.create_task(self.worker.enqueue_task(task))
        else:
            self.logger.error(f"App not started. Cannot start task: {task}")

    def update(self, event: BaseSocketMessage):
        self.logger.info(f"Received event: {event}")
        try:
            if WebsocketMessageTypes.START_RUN.equals(event.type):
                if not system_settings.enable_project_startup and event.run_type == RunType.PROJECT_RUN:
                    self.logger.error(f"Project startup is disabled.")
                    return
                event_message = event.message
                self.start_worker(event_message["id"], event.run_type, event_message)
                self.enqueue_task(AppTaskMessage(task=event.type, body=event.message))
            if WebsocketMessageTypes.START_PREDICTION.equals(event.type):
                event_message = event.message
                self.start_worker(event_message["id"], event.run_type, event_message)
                self.enqueue_task(AppTaskMessage(task=event.type, body=event.message))
        except Exception as e:
            if self.worker is not None:
                self.worker.update_status(RunStatusTypes.ERROR, str(e))
            self.logger.error(f"Error in workermanager manage server calls: {event} error {e}")
            traceback.print_exc()

import copy
import threading
import traceback
from collections import deque
from uuid import uuid4

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import WebsocketMessageTypes, RunType
from pyfedappwrap.engine.logger import WebSocketLogger
from pyfedappwrap.engine.observer.observer import Observer
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.socket.messages.app import AppTaskMessage
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.service.socket.socket import WebSocketClient
from pyfedappwrap.engine.service.upload.upload_client import UploadClient
from pyfedappwrap.engine.worker.run_dto import RunStatusTypes


class WorkerManager(Observer):
    def __init__(self, websocket_client: WebSocketClient, upload_client: UploadClient, lifecycle: EngineLifecycle):
        super().__init__("WorkerManager", websocket_client)
        self.lifecycle: EngineLifecycle = lifecycle
        self.websocket_client: WebSocketClient = websocket_client
        self.upload_client: UploadClient = upload_client
        self.logger = WebSocketLogger("WorkerManager", self.websocket_client)
        self.worker = None
        self.available_worker = None
        self._worker_lock = threading.RLock()
        self._pending_runs = deque()
        self.logger.info(f"WorkerManager initialized.")

    def start_worker(self, run_id, run_type: RunType, upload_client: UploadClient | None = None):
        if self.worker is not None:
            self.logger.error(f"Cannot start app, cause App is already running.")
            return

        if self.available_worker is None:
            self.logger.error(f"No App registered.")
            return
        worker = copy.deepcopy(self.available_worker)

        uuid = f"Run: {run_id}-{uuid4().__str__()}"
        worker.set_startup(self.websocket_client, upload_client if upload_client is not None else self.upload_client,
                           uuid, run_id, run_type,
                           self.lifecycle,
                           lambda error=None: self.stop_worker(error, expected_worker=worker))
        self.worker = worker

        # Start the worker in a separate thread
        worker_thread = threading.Thread(target=worker.start_app, daemon=True)
        worker_thread.start()
        self.logger.info(f"App started.")

    def stop_worker(self, error=None, expected_worker=None):
        with self._worker_lock:
            if expected_worker is not None and self.worker is not expected_worker:
                return
            self._stop_worker(error)

    def _stop_worker(self, error):
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
        if error is not None or self.lifecycle.is_stopping():
            self._pending_runs.clear()
        elif self._pending_runs:
            run_id, run_type, upload_client, task = self._pending_runs.popleft()
            self.start_worker(run_id, run_type, upload_client)
            self.enqueue_task(task)

    def get_worker_status(self):
        if self.worker is not None:
            return self.worker.get_status()
        return "not found"

    def enqueue_task(self, task):
        if self.worker is not None:
            self.worker.task_queue.put_nowait(task)
        else:
            self.logger.error(f"App not started. Cannot start task: {task}")

    def update(self, event: BaseSocketMessage):
        self.logger.info(f"Received event: {event.type}")
        try:
            if event.type in (WebsocketMessageTypes.START_RUN, WebsocketMessageTypes.START_PREDICTION):
                if (event.type == WebsocketMessageTypes.START_RUN
                        and not system_settings.enable_project_startup and event.run_type == RunType.PROJECT_RUN):
                    self.logger.error(f"Project startup is disabled.")
                    return
                event_message = event.message
                upload_client = self.upload_client.for_execution(event_message)
                task = AppTaskMessage(task=event.type, body=event_message)
                with self._worker_lock:
                    if self.worker is not None:
                        self._pending_runs.append((event_message["id"], event.run_type, upload_client, task))
                    else:
                        self.start_worker(event_message["id"], event.run_type, upload_client)
                        self.enqueue_task(task)

        except Exception as e:
            if self.worker is not None:
                self.worker.update_status(RunStatusTypes.ERROR, str(e))
            self.logger.error(f"Error in workermanager manage server calls: {event.type} error {e}")
            traceback.print_exc()

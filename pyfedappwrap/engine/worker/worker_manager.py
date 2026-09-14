import asyncio
import copy
import threading
import traceback
from uuid import uuid4

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import TestEmbedEnum, RunType
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
        self.logger.info(f"WorkerManager initialized.")

    def start_worker(self, run_id, run_type: RunType):
        if self.available_worker is None:
            self.logger.error(f"No App registered.")
            return

        if self.worker is None:
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
        else:
            self.logger.error(f"Cannot start app, cause App is already running.")

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
            if TestEmbedEnum.START_RUN.equals(event.type):
                if not system_settings.enable_project_startup and event.run_type == RunType.PROJECT_RUN:
                    self.logger.error(f"Project startup is disabled.")
                    return
                event_message = event.message
                self.start_worker(event_message["id"], event.run_type)
                self.enqueue_task(AppTaskMessage(task=str(event.type), body=event.message))
            if TestEmbedEnum.START_PREDICTION.equals(event.type):
                event_message = event.message
                self.start_worker(event_message["id"], event.run_type)
                self.enqueue_task(AppTaskMessage(task=str(event.type), body=event.message))
        except Exception as e:
            if self.worker is not None:
                self.worker.update_status(RunStatusTypes.ERROR, str(e))
            self.logger.error(f"Error in workermanager manage server calls: {event} error {e}")
            traceback.print_exc()

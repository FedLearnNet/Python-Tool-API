import os
import sys
import threading
from typing import Optional

import psutil

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.generator.generator import RandomTestGeneratorFactory
from pyfedappwrap.engine.helper.banner import print_banner
from pyfedappwrap.engine.helper.files_helper import ensure_system_directories
from pyfedappwrap.engine.logger import WebSocketLogger, WebSocketConsoleHandler
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.keycloak.keycloak import KeycloakClient
from pyfedappwrap.engine.service.socket.socket import WebSocketClient
from pyfedappwrap.engine.service.upload.upload_client import UploadClient
from pyfedappwrap.engine.tests.test_socket import TestSocketClient
from pyfedappwrap.engine.tests.test_upload_client import TestUploadClient
from pyfedappwrap.engine.watcher.cpu_watcher import SystemWatcher
from pyfedappwrap.engine.watcher.file_watcher import FileWatcher
from pyfedappwrap.engine.watcher.run_timing import mark_engine_connected
from pyfedappwrap.engine.worker.federated_worker_manager import FederatedWorkerManager
from pyfedappwrap.engine.worker.worker_manager import WorkerManager
from pyfedappwrap.learning.base_app import BaseApp
from pyfedappwrap.learning.federated import BaseFederatedApp
from pyfedappwrap.types.transformation.base_transformer import BaseTransformerAPP
from pyfedappwrap.types.transformation.config_writer import write_transformer_config


class FedDBEngine(threading.Thread):
    def __init__(self, *, test_mode: Optional[bool] = None):
        super().__init__(daemon=True)
        self.lifecycle: EngineLifecycle = EngineLifecycle()
        if test_mode is not None:
            self.lifecycle.test_mode = test_mode
        else:
            self.lifecycle.test_mode = system_settings.test_mode
        self.api_key = system_settings.app_api_key
        if system_settings.app_key is not None:
            self.token = system_settings.app_key
        elif self.api_key is not None:
            self.token = None
        elif self.lifecycle.test_mode:
            self.token = "TEST_MODE_TOKEN"
        else:
            self.token = KeycloakClient().get_token()
        # Initialize WebSocketClient, FileWatcher, and SystemWatcher with stop events
        self.test_generator = RandomTestGeneratorFactory()
        self.ws_client = WebSocketClient(
            f"{system_settings.ws_url}{system_settings.app_id}{system_settings.ws_path}",
            self.lifecycle,
            self.token,
            self.api_key,
        )
        self.upload_client = UploadClient(self.token, self.api_key)
        if self.lifecycle.test_mode:
            self.ws_client = TestSocketClient(self.test_generator, self.lifecycle)
            self.upload_client = TestUploadClient("TEST_MODE_TOKEN")

        self.file_watcher = FileWatcher(system_settings.config_settings_path, self.ws_client,
                                        self.lifecycle)
        self.system_watcher = SystemWatcher(self.lifecycle, self.ws_client)
        self._aggregators: dict[str, object] = {}

        self.process = psutil.Process(os.getpid())
        self.logger = WebSocketLogger("WorkerManager", self.ws_client)
        sys.stdout = WebSocketConsoleHandler(self.ws_client)
        self.worker_manager = WorkerManager(self.ws_client, self.upload_client, self.lifecycle)
        self.federated_worker_manager = FederatedWorkerManager(
            self.ws_client,
            self.lifecycle,
            self.upload_client,
        )

        if self.lifecycle.test_mode:
            print_banner("TEST MODE ENABLED", [
                "The engine is running in test mode. No real connections will be made.",
                "Use this mode for local testing and development only."
            ])
        else:
            print_banner("FEDDB ENGINE STARTING", [
                "The engine is starting and will connect to the FedDB server.",
                "Ensure that your network connection is active."
            ])

    def run(self):
        try:
            ensure_system_directories()

            if self.lifecycle.test_mode:
                print("Starting test data generator...")
                self.test_generator.mange_all()
                self.test_generator.generate()

            self.ws_client.start()
            # Websocket is up: mark the engine "connected" reference for run-lifecycle timing.
            mark_engine_connected()
            if system_settings.dev_mode and system_settings.enable_config_sync:
                print("Starting file watcher...")
                self.file_watcher.start()
            if system_settings.trace_performance:
                print("Starting system watcher...")
                self.system_watcher.start()

            print("FedDBEngine is running in the background. Press Ctrl+C to stop.")

            while not self.lifecycle.is_stopping():
                self.lifecycle.stop_event_wait(1)

            self.cleanup()

        except KeyboardInterrupt:
            print("KeyboardInterrupt received. Stopping FedDBEngine...")
            self.stop()
            self.cleanup()

        except Exception as e:
            print_banner("FEDDB ENGINE CRASH", [
                "An unhandled exception occurred.",
                f"{type(e).__name__}: {e}",
                "The engine will stop now."
            ])
            try:
                self.lifecycle.stop()
                self.lifecycle.request_exit()
            finally:
                if self.lifecycle.test_mode:
                    os._exit(1)
                raise

    def stop(self):
        print_banner("STOPPING FEDDB ENGINE", [
            "The engine is stopping. All background processes will be terminated.",
            "Test files and temporary data will be cleaned up."
        ])
        self.lifecycle.stop()
        self.lifecycle.request_exit()

    def cleanup(self):
        if self.test_generator.has_manged_generator():
            self.test_generator.clean_up()

    def wait_until_stop(self):
        print("Engine is now running in the background.")
        print("Press Ctrl + C to stop the engine.")
        try:
            while not self.lifecycle.is_exiting():
                # Avoid busy spinning and also detect unexpected thread death.
                if not self.is_alive() and not self.lifecycle.is_stopping():
                    # Engine thread died unexpectedly; in test mode we should fail hard.
                    if self.lifecycle.test_mode:
                        os._exit(1)
                    break
                self.lifecycle.stop_event_wait(0.2)
        except KeyboardInterrupt:
            print("Exit by KeyboardInterrupt")
            self.stop()
            self.cleanup()

        exit_payload = self.lifecycle.exit_payload
        if self.lifecycle.test_mode:
            assert exit_payload is None, "In test mode, exit_payload should be None"
        return exit_payload

    def register(self, app: BaseApp):
        self.worker_manager.available_worker = app
        if self.lifecycle.test_mode and app.get_test_data() is not None:
            print("Registering test data...")
            self.test_generator.copy_for_predefined(app.get_test_data())
        if self.lifecycle.test_mode and app.get_test_hyperparams() is not None:
            self.test_generator.hyperparams = app.get_test_hyperparams()

    def register_federated(self, app: BaseFederatedApp):
        self.federated_worker_manager.available_app = app
        self.federated_worker_manager.set_aggregators(self._aggregators)
        if self.lifecycle.test_mode and hasattr(self.ws_client, "federated_test_mode"):
            self.ws_client.federated_test_mode = True
        self.register(app)

    def register_transformer(self, app: BaseTransformerAPP):
        self.worker_manager.available_worker = app
        if system_settings.dev_mode:
            write_transformer_config(system_settings.config_settings_path, app)

    def register_aggregator(self, aggregator, key: str = "default"):
        self._aggregators[key] = aggregator
        self.federated_worker_manager.register_aggregator(aggregator, key)

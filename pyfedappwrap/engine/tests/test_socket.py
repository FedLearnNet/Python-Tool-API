import asyncio
import logging
import threading

from pyfedappwrap.engine.config.config import AppType
from pyfedappwrap.engine.config.config_handler import load_tool_type
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.events.internal_events import handle_internal_event
from pyfedappwrap.engine.generator.generator import RandomTestGeneratorFactory
from pyfedappwrap.engine.observer.subject import Subject
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.socket.messages.app import SendFinishRunDTO
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.service.socket.messages.federated import SendFederatedFinishRunDTO
from pyfedappwrap.engine.tests.events import TestEvents


class TestSocketClient(Subject, threading.Thread):
    def __init__(self, test_data: RandomTestGeneratorFactory, lifecycle: EngineLifecycle):
        Subject.__init__(self)
        threading.Thread.__init__(self, daemon=True)  # Run as a daemon thread
        self.loop = asyncio.new_event_loop()
        self.lifecycle = lifecycle
        self.sleep_interval = 0.5
        self.test_data = test_data
        self.event_generator = TestEvents(self.test_data)
        self.events: list[BaseSocketMessage] = []
        self.type = load_tool_type(system_settings.config_settings_path)
        self.federated_test_mode = False

    def run(self):
        if self.federated_test_mode:
            self.events.append(self.event_generator.default_start_federated_test_run_task())
        elif self.type and self.type == AppType.ANALYSIS:
            self.events.append(self.event_generator.default_start_run_task())
        else:
            self.events.append(self.event_generator.default_start_prediction_task())

        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.mock_messages())

    def stop(self):
        logging.info("Stopping Event Loop")

    async def mock_messages(self):
        await asyncio.sleep(self.sleep_interval)
        for event in self.events:
            if self.lifecycle.is_stopping():
                break
            self.handle_event(event)
            await asyncio.sleep(self.sleep_interval)

    def handle_event(self, event: BaseSocketMessage):
        handle_internal_event(event, self.send)
        self.set_state(event)

    def handle_error(self, message):
        logging.info(f"Error handling message: {message}")
        self.lifecycle.add_error(message)

    def send(self, message: BaseSocketMessage):
        if isinstance(message, (SendFinishRunDTO, SendFederatedFinishRunDTO)):
            self.lifecycle.request_finish()

    def send_silent(self, message):
        pass

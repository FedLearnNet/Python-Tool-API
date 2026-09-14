import asyncio
import json
import logging
import threading
import traceback

import websockets

from pyfedappwrap.engine.events.internal_events import handle_internal_event
from pyfedappwrap.engine.observer.subject import Subject
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage


class WebSocketClient(Subject, threading.Thread):
    def __init__(self, uri, lifecycle: EngineLifecycle, token, api_key=None):
        Subject.__init__(self)
        threading.Thread.__init__(self, daemon=True)  # Run as a daemon thread
        self.uri = uri
        self.websocket = None
        self.loop = asyncio.new_event_loop()
        self.lifecycle = lifecycle
        self.additional_headers = {}
        if token:
            logging.info("Use Authorization Bearer token")
            self.additional_headers["Authorization"] = "Bearer " + token
        if api_key:
            logging.info("Use Authorization X-API-Key")
            self.additional_headers["X-API-Key"] = api_key
        if not self.additional_headers:
            logging.info("WebSocketClient initialized without authentication headers.")

        self.retry_interval = 5

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._manage_connection())
        self.loop.set_exception_handler(self.exception_handler)

    def exception_handler(self, _loop, context):
        exception = context.get("exception")
        message = context.get("message", "Unknown error")
        logging.info(f"Exception in Event Loop: {message}")
        if exception:
            logging.info(f"Exception Details: {exception}")
            self.lifecycle.add_error(exception)
        else:
            self.lifecycle.add_error(message)

    def stop(self):
        if self.websocket:
            self.websocket.close()

    async def _manage_connection(self):
        """Manage the WebSocket connection with automatic retries."""
        while not self.lifecycle.is_stopping():
            try:
                await self.connect()
            except websockets.ConnectionClosed:
                logging.info("WebSocket connection closed, retrying...")
            except Exception as e:
                logging.info(f"Error in WebSocket connection: {e}")
                traceback.print_exc()

            # Wait before retrying
            if not self.lifecycle.is_stopping():
                await asyncio.sleep(self.retry_interval)

    async def connect(self):
        """Connect to the WebSocket server and start listening."""
        logging.info(f"Connecting to WebSocket server: {self.uri}")
        logging.info("Configured WebSocket authentication headers: %s", list(self.additional_headers))

        async with websockets.connect(self.uri,
                                      additional_headers=self.additional_headers,
                                      open_timeout=30) as websocket:
            self.websocket = websocket
            await self.receive_messages()

    async def receive_messages(self):
        """Handle incoming WebSocket messages."""
        while not self.lifecycle.is_stopping():
            try:
                message = await self.websocket.recv()
                logging.info(f"Received message: {message}")
                try:
                    event_dto = BaseSocketMessage.model_validate_json(message)
                    self.handle_event(event_dto)
                except json.JSONDecodeError:
                    self.handle_error(message)
            except websockets.ConnectionClosed:
                logging.info("WebSocket connection closed.")
                break
            except Exception as e:
                logging.info(f"Error receiving message: {e}")
                break

    def handle_event(self, event: BaseSocketMessage):
        handle_internal_event(event, self.send)
        self.set_state(event)

    def handle_error(self, message):
        logging.info(f"Error handling message: {message}")
        self.lifecycle.add_error(message)

    def send(self, message: BaseSocketMessage):
        """Send messages through WebSocket."""
        if self.websocket is None:
            logging.info("WebSocket connection is not established")
        else:
            logging.info(f"Sending message: {message}")
            message_json = message.to_json()
            asyncio.run_coroutine_threadsafe(self.websocket.send(message_json), self.loop)

    def send_silent(self, message):
        """Send messages through WebSocket."""
        if self.websocket is None:
            return
        asyncio.run_coroutine_threadsafe(self.websocket.send(message.to_json()), self.loop)

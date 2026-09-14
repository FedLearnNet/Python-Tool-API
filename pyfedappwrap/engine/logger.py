import logging
import sys
import traceback

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import RunType
from pyfedappwrap.engine.service.socket.messages.message import TestRunMessageLogDTO, \
    SendConsoleMessage, SendLogDTO
from pyfedappwrap.engine.service.socket.messages.monitor import ConsoleStdOutDTO


class WebSocketLogger(logging.Logger):
    def __init__(self, name, websocket_client, run_id=None, run_type=RunType.NOT_DEFINED,
                 level=logging.DEBUG, process_name=None, worker_id=None):
        """Initialize the WebSocketLogger with a WebSocket client and logging level."""
        super().__init__(name, level)
        ws_handler = WebSocketHandler(
            websocket_client,
            name,
            run_id,
            run_type,
            process_name,
            worker_id,
        )
        # Create a formatter for log messages
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ws_handler.setFormatter(formatter)
        # Add the handler to this logger
        self.addHandler(ws_handler)


class WebSocketHandler(logging.Handler):
    def __init__(self, websocket_client, name, run_id, run_type=RunType.NOT_DEFINED,
                 process_name=None, worker_id=None):
        """Custom logging handler to send logs to WebSocket."""
        super().__init__()
        self.websocket_client = websocket_client
        self.name = name
        self.run_id = run_id
        self.run_type = run_type
        self.process_name = process_name
        self.worker_id = worker_id

    def emit(self, record):
        """Send log message to WebSocket and console."""
        try:
            stack_trace = record.stack_info
            group = ''
            caller = record.name
            severity = record.levelname
            run_id = self.run_id
            if run_id is None:
                return  # Skip if no run_id is provided
            message_txt = getattr(record, 'message', None) or record.msg
            if message_txt is None:
                return # Skip if no message is provided
            log = TestRunMessageLogDTO(
                process=self.process_name or record.processName,
                message=message_txt,
                run_id=run_id,
                worker_id=self.worker_id,
                severity=severity,
                caller=caller,
                stack_trace=stack_trace,
                group=group
            )

            message = SendLogDTO(message=log, run_type=self.run_type)
            self.websocket_client.send(message)
        except Exception:
            print(record)
            traceback.print_exc()


class WebSocketConsoleHandler(object):
    def __init__(self, websocket_client):
        self.websocket_client = websocket_client
        self.stdout = sys.stdout

    def write(self, msg):
        self.stdout.write(msg)
        log = ConsoleStdOutDTO(
            msg=msg
        )

        if system_settings.send_console_log:
            message = SendConsoleMessage(message=log)
            self.websocket_client.send_silent(message)

    def flush(self):
        """Flush the output stream. Required for sys.stdout compatibility."""
        if hasattr(self.stdout, 'flush'):
            self.stdout.flush()

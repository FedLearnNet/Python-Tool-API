import threading
import time

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from pyfedappwrap.engine.config.config_handler import load_config
from pyfedappwrap.engine.logger import WebSocketLogger
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.socket.messages.config import SendConfigChangedDTO


class FileWatcher(threading.Thread, FileSystemEventHandler):
    def __init__(self, file_path, websocket_client, lifecycle: EngineLifecycle):
        threading.Thread.__init__(self)
        FileSystemEventHandler.__init__(self)
        self.file_path = file_path
        self.websocket_client = websocket_client
        self.lifecycle = lifecycle
        self.observer = None
        self.logger = WebSocketLogger("FileWatcher", self.websocket_client)


    def on_modified(self, event):
        if event.src_path.endswith(self.file_path) or event.src_path.endswith("README.md"):
            self.logger.info(f"File {event.src_path} has been modified")

            model = load_config(self.file_path)
            if model is not None:
                dto = SendConfigChangedDTO(message=model)
                self.websocket_client.send(dto)

    def run(self):
        self.start_watching()

    def start_watching(self):
        self.logger.info(f"Watching file: {self.file_path}")
        self.observer = Observer()
        self.observer.schedule(self, path='.', recursive=False)
        self.observer.start()
        while not self.lifecycle.is_stopping():
            time.sleep(1)
        self.stop_watching()

    def stop_watching(self):
        self.logger.info(f"Stopped watching file: {self.file_path}")
        if self.observer is None:
            return
        self.observer.stop()
        self.observer.join()
        self.observer = None

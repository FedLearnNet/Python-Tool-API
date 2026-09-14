import os
import time
import threading

import psutil

from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.socket.messages.monitor import PerformanceDTO
from pyfedappwrap.engine.service.socket.socket_dto import ClientPerformanceDTO


class SystemWatcher(threading.Thread):

    def __init__(self, lifecycle: EngineLifecycle, ws_client, name="Main Loop"):
        super(SystemWatcher, self).__init__()
        self.process = psutil.Process(os.getpid())
        self.name = name
        self.lifecycle = lifecycle
        self.app_start_time = time.time()
        self.ws_client = ws_client

    def run(self):
        self.track_cpu_usage()

    def track_cpu_usage(self):
        while not self.lifecycle.is_stopping():
            performance: PerformanceDTO = self.get_performance(self.process, self.name)
            message = ClientPerformanceDTO(message=performance)
            #print(f"[Main] Sending message: {message}")
            self.ws_client.send_silent(message)
            time.sleep(1)

    def seconds_since_start(self):
        current_unix_time = time.time()
        return int(current_unix_time - self.app_start_time)

    def get_performance(self, process, process_name) -> PerformanceDTO:
        cpu_usage = process.cpu_percent(interval=1)
        memory_info = process.memory_info()
        memory_usage_mb = memory_info.rss / (1024 * 1024)
        total_memory = psutil.virtual_memory().total / (1024 * 1024)
        memory_usage_percent = (memory_usage_mb / total_memory) * 100
        current_unix_time = self.seconds_since_start()
        return PerformanceDTO(cpu=cpu_usage,
                              memory=memory_usage_percent,
                              process=process_name,
                              timestamp=current_unix_time)
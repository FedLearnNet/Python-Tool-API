from abc import ABC, abstractmethod


def on_init(method):
    method._on_init = True
    return method


def on_start(method):
    method._on_start = True
    return method


def on_end(method):
    method._on_end = True
    return method


class AppRunnable(ABC):

    def run(self):
        self.on_init()
        self.on_start()
        self.on_end()

    def on_start(self):
        for name in dir(self):
            method = getattr(self, name)
            if callable(method) and getattr(method, '_on_start', False):
                method()

    def on_end(self):
        for name in dir(self):
            method = getattr(self, name)
            if callable(method) and getattr(method, '_on_end', False):
                method()

    def on_init(self):
        for name in dir(self):
            method = getattr(self, name)
            if callable(method) and getattr(method, '_on_init', False):
                method()

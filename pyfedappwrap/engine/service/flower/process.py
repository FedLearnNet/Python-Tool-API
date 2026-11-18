"""Starts and supervises exactly one Flower OS process (`flower-superlink` or
`flower-supernode`) as a child of the engine process.

Flower's own recommended production topology runs SuperLink, each SuperNode, and (under
`--isolation process`) a separate SuperExec per role as their own containers/processes. This
platform deliberately doesn't follow that: every attempt (federated participant or aggregator)
is already one container, so the engine starts its one Flower process in the default,
non-isolated SuperExec mode - SuperExec auto-starts embedded as a child of whichever process
this supervises, so there's only ever one child process tree to manage here, not three.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from typing import Optional, Sequence


class FlowerProcessError(RuntimeError):
    """The supervised Flower process exited (crashed or was never started successfully)."""


class FlowerProcessSupervisor:
    """Supervises one subprocess, started by `binary` + `args`. Not reentrant: one instance per
    process it supervises."""

    def __init__(self, binary: str, args: Sequence[str]):
        self.binary = binary
        self.args = list(args)
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise FlowerProcessError(f"{self.binary} is already running (pid {self._process.pid})")
            logging.info("Starting %s %s", self.binary, " ".join(self.args))
            self._process = subprocess.Popen(  # noqa: S603 - binary/args are our own config, not user input
                [self.binary, *self.args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

    def is_alive(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def exit_code(self) -> Optional[int]:
        with self._lock:
            return None if self._process is None else self._process.poll()

    def check_alive(self) -> None:
        """Raises FlowerProcessError if the process was started and has since exited."""
        with self._lock:
            if self._process is None:
                raise FlowerProcessError(f"{self.binary} was never started")
            exit_code = self._process.poll()
            if exit_code is not None:
                output = self._process.stdout.read() if self._process.stdout else ""
                raise FlowerProcessError(
                    f"{self.binary} exited with code {exit_code}"
                    + (f": {output.strip()}" if output.strip() else "")
                )

    def stop(self, *, timeout: float = 10.0) -> None:
        """Graceful shutdown: SIGTERM, then SIGKILL if it doesn't exit in time. A no-op if the
        process was never started or already exited."""
        with self._lock:
            process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logging.warning("%s (pid %d) ignored SIGTERM, killing it", self.binary, process.pid)
            process.kill()
            process.wait(timeout=timeout)

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
import os
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Mapping, Optional, Sequence

# How many of the process's last output lines an error message carries.
OUTPUT_TAIL_LINES = 50


class FlowerProcessError(RuntimeError):
    """The supervised Flower process exited (crashed or was never started successfully)."""


class FlowerProcessSupervisor:
    """Supervises one subprocess, started by `binary` + `args`. Not reentrant: one instance per
    process it supervises."""

    def __init__(self, binary: str, args: Sequence[str], *, cwd: Optional[Path] = None,
                 extra_env: Optional[Mapping[str, str]] = None):
        self.binary = binary
        self.args = list(args)
        self.cwd = cwd
        self.extra_env = dict(extra_env or {})
        self._process: Optional[subprocess.Popen] = None
        self._output_tail: deque[str] = deque(maxlen=OUTPUT_TAIL_LINES)
        self._drain_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise FlowerProcessError(f"{self.binary} is already running (pid {self._process.pid})")
            logging.info("Starting %s %s", self.binary, " ".join(self.args))
            env = {**os.environ, **self.extra_env} if self.extra_env else None
            self._output_tail.clear()
            self._process = subprocess.Popen(  # noqa: S603 - binary/args are our own config, not user input
                [self.binary, *self.args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=self.cwd,
                env=env,
            )
            # The pipe must be read continuously: once its OS buffer (~64 KiB) fills up, the
            # child blocks on its next log line and a long training run silently hangs.
            self._drain_thread = threading.Thread(
                target=self._drain, args=(self._process,),
                name=f"{self.binary}-output", daemon=True)
            self._drain_thread.start()

    def _drain(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            line = line.rstrip()
            if line:
                self._output_tail.append(line)
                logging.info("[%s] %s", self.binary, line)

    def _wait_for_output(self, timeout: float = 2.0) -> str:
        """The last lines the process wrote, once its output has been read to the end (or after
        `timeout`, if a grandchild still holds the pipe open)."""
        if self._drain_thread is not None:
            self._drain_thread.join(timeout)
        return "\n".join(self._output_tail)

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
                output = self._wait_for_output()
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

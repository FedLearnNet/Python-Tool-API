"""Lifecycle timing for a single tool run.

Records the six lifecycle timestamps that separate the tool's scientific compute time
(Runtime) from the platform-added time (Runtime Overhead):

    engine_start ─▶ connected ─▶ run_received ─▶ compute_start ─▶ compute_end ─▶ outputs_transferred
    (PENDING)      (INITIALIZED)  (STARTED)       (enter RUNNING)  (fn returns)    (FINISHED)

Derived metrics:
    runtime           = compute_end - compute_start          (tool scientific fn only)
    overhead_startup  = compute_start - engine_start         (container/engine/auth/validation)
    overhead_teardown = outputs_transferred - compute_end    (output transfer + cleanup)
    overhead_total    = overhead_startup + overhead_teardown
    wall_total        = outputs_transferred - engine_start   (== runtime + overhead_total)

All durations use a monotonic clock; a single wall-clock stamp (engine_start) is kept for
display only. Any timestamp that is never marked (e.g. on the ERROR path) stays ``None`` and
every derived metric that depends on it is ``None`` too.
"""
import time
from typing import Optional

# Captured as soon as this module is first imported by the engine. In PoSyMed each tool run
# executes in its own container, so this monotonic reference is a close proxy for
# container/process start; the container-start portion folds into overhead_startup
# (cold- vs. warm-start attribution is a separate, out-of-scope concern).
_ENGINE_START_MONO: float = time.monotonic()
_ENGINE_START_WALL: float = time.time()

# Set once, when the engine's websocket connection is established (before any run arrives).
_ENGINE_CONNECTED_MONO: Optional[float] = None


def mark_engine_connected() -> None:
    """Record the moment the engine's websocket connection is established.

    Idempotent: only the first call within a process is kept, matching the one-container-per-run
    model where the connection precedes the single run.
    """
    global _ENGINE_CONNECTED_MONO
    if _ENGINE_CONNECTED_MONO is None:
        _ENGINE_CONNECTED_MONO = time.monotonic()


def _ms(delta_seconds: Optional[float]) -> Optional[int]:
    if delta_seconds is None:
        return None
    return int(round(delta_seconds * 1000))


class RunTiming:
    """Collects lifecycle timestamps for one tool run and derives the timing metrics."""

    def __init__(self, *, engine_start: Optional[float] = None):
        # engine_start defaults to the process-boot reference so container start + engine init
        # are attributed to overhead_startup.
        self.engine_start: float = engine_start if engine_start is not None else _ENGINE_START_MONO
        self.engine_start_wall: float = _ENGINE_START_WALL
        self.connected: Optional[float] = _ENGINE_CONNECTED_MONO
        self.run_received: Optional[float] = None
        self.compute_start: Optional[float] = None
        self.compute_end: Optional[float] = None
        self.outputs_transferred: Optional[float] = None

    # --- marks ---------------------------------------------------------------
    def mark_run_received(self) -> None:
        if self.run_received is None:
            self.run_received = time.monotonic()

    def mark_compute_start(self) -> None:
        """Mark entry into the tool's scientific function (RUNNING transition)."""
        self.compute_start = time.monotonic()

    def mark_compute_end(self) -> None:
        """Mark the return of the tool's scientific function. Not called if the fn raised."""
        self.compute_end = time.monotonic()

    def mark_outputs_transferred(self) -> None:
        """Mark completion of output transfer / persistence (FINISHED transition)."""
        self.outputs_transferred = time.monotonic()

    # --- derived metrics (seconds) -------------------------------------------
    @property
    def runtime(self) -> Optional[float]:
        if self.compute_start is None or self.compute_end is None:
            return None
        return self.compute_end - self.compute_start

    @property
    def overhead_startup(self) -> Optional[float]:
        if self.compute_start is None:
            return None
        return self.compute_start - self.engine_start

    @property
    def overhead_teardown(self) -> Optional[float]:
        if self.compute_end is None or self.outputs_transferred is None:
            return None
        return self.outputs_transferred - self.compute_end

    @property
    def overhead_total(self) -> Optional[float]:
        if self.overhead_startup is None or self.overhead_teardown is None:
            return None
        return self.overhead_startup + self.overhead_teardown

    @property
    def wall_total(self) -> Optional[float]:
        if self.outputs_transferred is None:
            return None
        return self.outputs_transferred - self.engine_start

    # --- metrics as milliseconds (wire format) -------------------------------
    def runtime_ms(self) -> Optional[int]:
        return _ms(self.runtime)

    def overhead_ms(self) -> dict:
        """Overhead durations in ms. Always reported by the wrapper; whether they are persisted
        and displayed is decided by the learning-api (posymed.runtime.overhead.enabled)."""
        return {
            "overhead_startup_ms": _ms(self.overhead_startup),
            "overhead_teardown_ms": _ms(self.overhead_teardown),
            "overhead_total_ms": _ms(self.overhead_total),
            "wall_total_ms": _ms(self.wall_total),
        }

    def timings_dict(self) -> dict:
        """Timings keyed by metric name (matching the backend RunTimingMetric enum), in ms.
        Entries that could not be measured (None, e.g. on the ERROR path) are omitted."""
        values = {
            "RUNTIME": self.runtime_ms(),
            "OVERHEAD_STARTUP": _ms(self.overhead_startup),
            "OVERHEAD_TEARDOWN": _ms(self.overhead_teardown),
            "OVERHEAD_TOTAL": _ms(self.overhead_total),
        }
        return {key: value for key, value in values.items() if value is not None}

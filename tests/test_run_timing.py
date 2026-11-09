import time

import pytest

from pyfedappwrap.engine.watcher.run_timing import RunTiming


def _fake_tool(seconds: float) -> str:
    """Stand-in for a tool's scientific function: does nothing but take `seconds` to run."""
    time.sleep(seconds)
    return "output"


def test_runtime_brackets_only_the_tool_function():
    # Simulate the full lifecycle: startup work, the tool fn, then output transfer.
    t = RunTiming(engine_start=time.monotonic())

    time.sleep(0.05)  # container/engine/auth/validation → startup overhead
    t.mark_compute_start()
    _fake_tool(0.10)  # the only thing runtime should measure
    t.mark_compute_end()
    time.sleep(0.05)  # output transfer + cleanup → teardown overhead
    t.mark_outputs_transferred()

    # runtime tracks the sleep-based tool, not the surrounding overhead.
    assert t.runtime == pytest.approx(0.10, abs=0.03)
    assert t.overhead_startup > 0
    assert t.overhead_teardown > 0
    # The surrounding overhead is clearly separated from the compute time.
    assert t.overhead_startup == pytest.approx(0.05, abs=0.03)
    assert t.overhead_teardown == pytest.approx(0.05, abs=0.03)


def test_wall_total_equals_runtime_plus_overhead():
    t = RunTiming(engine_start=time.monotonic())
    time.sleep(0.02)
    t.mark_compute_start()
    _fake_tool(0.05)
    t.mark_compute_end()
    time.sleep(0.02)
    t.mark_outputs_transferred()

    # Sanity from the timing model: wall_total == runtime + overhead_total (within a few ms).
    assert t.wall_total == pytest.approx(t.runtime + t.overhead_total, abs=0.005)
    # Same invariant on the ms-rounded wire values.
    o = t.overhead_ms()
    assert abs(o["wall_total_ms"] - (t.runtime_ms() + o["overhead_total_ms"])) <= 2

    # The metric-keyed timings map carries all four metrics for a complete run.
    timings = t.timings_dict()
    assert set(timings) == {"RUNTIME", "OVERHEAD_STARTUP", "OVERHEAD_TEARDOWN", "OVERHEAD_TOTAL"}
    assert timings["RUNTIME"] == t.runtime_ms()
    assert abs(timings["OVERHEAD_TOTAL"] - (timings["OVERHEAD_STARTUP"] + timings["OVERHEAD_TEARDOWN"])) <= 1


def test_error_path_records_partial_timings():
    # Tool raised before returning: compute_end / outputs_transferred are never marked.
    t = RunTiming(engine_start=time.monotonic())
    t.mark_compute_start()

    # Later timestamps are null; metrics depending on them are null too.
    assert t.runtime is None
    assert t.runtime_ms() is None
    assert t.overhead_teardown is None
    assert t.overhead_total is None
    assert t.wall_total is None
    # Startup is still known (compute_start was reached) and does not crash.
    assert t.overhead_startup is not None
    assert t.overhead_ms()["overhead_startup_ms"] is not None
    # The timings map omits unmeasured metrics (no RUNTIME/teardown/total on the error path).
    timings = t.timings_dict()
    assert "RUNTIME" not in timings
    assert "OVERHEAD_TOTAL" not in timings
    assert timings["OVERHEAD_STARTUP"] is not None


def test_no_timestamps_yields_all_none():
    # A run that never started computing (e.g. failed during validation) has no runtime.
    t = RunTiming(engine_start=time.monotonic())
    assert t.runtime is None
    assert t.overhead_startup is None
    assert t.overhead_total is None
    assert t.wall_total is None

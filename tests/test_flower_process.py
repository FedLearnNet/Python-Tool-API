import subprocess
import sys
import time

import pytest

from pyfedappwrap.engine.service.flower.process import FlowerProcessError, FlowerProcessSupervisor


def long_running_args():
    # A real child process (not mocked) that sleeps, so start/stop/is_alive exercise the real
    # subprocess machinery rather than a mock standing in for it.
    return [sys.executable, "-c", "import time; time.sleep(30)"]


def test_is_alive_false_before_start_and_true_after():
    supervisor = FlowerProcessSupervisor(sys.executable, ["-c", "import time; time.sleep(30)"])
    assert not supervisor.is_alive()

    supervisor.start()
    try:
        assert supervisor.is_alive()
    finally:
        supervisor.stop()
    assert not supervisor.is_alive()


def test_check_alive_raises_before_start():
    supervisor = FlowerProcessSupervisor("flower-superlink", ["--insecure"])
    with pytest.raises(FlowerProcessError, match="never started"):
        supervisor.check_alive()


def test_check_alive_raises_with_the_exit_code_and_output_once_the_process_exits():
    supervisor = FlowerProcessSupervisor(sys.executable, ["-c", "print('boom'); exit(1)"])
    supervisor.start()
    supervisor._process.wait(timeout=5)

    with pytest.raises(FlowerProcessError, match="exited with code 1: boom"):
        supervisor.check_alive()


def test_starting_twice_while_alive_raises():
    supervisor = FlowerProcessSupervisor(sys.executable, ["-c", "import time; time.sleep(30)"])
    supervisor.start()
    try:
        with pytest.raises(FlowerProcessError, match="already running"):
            supervisor.start()
    finally:
        supervisor.stop()


def test_stop_is_a_no_op_when_never_started():
    supervisor = FlowerProcessSupervisor("flower-superlink", ["--insecure"])
    supervisor.stop()  # must not raise


def test_stop_terminates_a_running_process():
    supervisor = FlowerProcessSupervisor(sys.executable, ["-c", "import time; time.sleep(30)"])
    supervisor.start()
    assert supervisor.is_alive()

    supervisor.stop()

    assert not supervisor.is_alive()
    assert supervisor.exit_code() is not None


def test_stop_kills_a_process_that_ignores_sigterm():
    # Python ignores SIGTERM by default only if we install a handler for it; simulate a
    # stubborn process by trapping SIGTERM and sleeping anyway.
    supervisor = FlowerProcessSupervisor(sys.executable, [
        "-c",
        "import signal, time; signal.signal(signal.SIGTERM, lambda *a: None); time.sleep(30)",
    ])
    supervisor.start()
    time.sleep(0.3)  # let the signal handler install before we send SIGTERM

    supervisor.stop(timeout=1.0)

    assert not supervisor.is_alive()

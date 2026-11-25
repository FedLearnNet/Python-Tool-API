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


def test_a_process_that_writes_more_than_a_pipe_buffer_does_not_block():
    # ~1 MiB of output: without the supervisor reading it continuously, the child blocks once
    # the OS pipe buffer (~64 KiB) is full and never exits.
    supervisor = FlowerProcessSupervisor(sys.executable, [
        "-c", "import sys\nfor i in range(20000): print('x' * 50)\nprint('done')",
    ])
    supervisor.start()
    try:
        supervisor._process.wait(timeout=10)
    finally:
        supervisor.stop()
    assert supervisor.exit_code() == 0


def test_check_alive_reports_only_the_tail_of_a_long_output():
    supervisor = FlowerProcessSupervisor(sys.executable, [
        "-c", "for i in range(500): print(f'line {i}')\nexit(3)",
    ])
    supervisor.start()
    supervisor._process.wait(timeout=10)

    with pytest.raises(FlowerProcessError) as info:
        supervisor.check_alive()

    message = str(info.value)
    assert "exited with code 3" in message
    assert "line 499" in message
    assert "line 0\n" not in message


def test_the_process_runs_in_the_given_directory_with_the_extra_env(tmp_path):
    supervisor = FlowerProcessSupervisor(sys.executable, [
        "-c", "import os; open('seen.txt', 'w').write(os.environ['MODEL_DIR'] + '|' + os.environ['PATH'])",
    ], cwd=tmp_path, extra_env={"MODEL_DIR": "/models"})
    supervisor.start()
    supervisor._process.wait(timeout=10)

    model_dir, path = (tmp_path / "seen.txt").read_text().split("|", 1)
    assert model_dir == "/models"
    assert path  # the rest of the environment is kept, not replaced

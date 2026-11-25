import threading
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from pyfedappwrap.engine.service.flower import lifecycle as lifecycle_module
from pyfedappwrap.engine.service.flower.cli import FlowerCliError
from pyfedappwrap.engine.service.flower.lifecycle import FlowerRunLifecycle
from pyfedappwrap.engine.service.flower.process import FlowerProcessError
from pyfedappwrap.learning.federated.flower_app import FlowerApp


class FakeSupervisor:
    """Stands in for FlowerProcessSupervisor so these tests exercise lifecycle's own
    orchestration logic without starting real OS processes."""

    instances: list["FakeSupervisor"] = []

    def __init__(self, binary, args, *, cwd=None, extra_env=None):
        self.binary = binary
        self.args = args
        self.cwd = cwd
        self.extra_env = extra_env or {}
        self.started = False
        self.stopped = False
        self.alive = True
        FakeSupervisor.instances.append(self)

    def start(self):
        self.started = True

    def check_alive(self):
        if not self.alive:
            raise FlowerProcessError(f"{self.binary} exited with code 1")

    def is_alive(self):
        return self.alive

    def stop(self, timeout=10.0):
        self.stopped = True
        self.alive = False


@pytest.fixture(autouse=True)
def fake_supervisor(monkeypatch):
    FakeSupervisor.instances = []
    monkeypatch.setattr(lifecycle_module, "FlowerProcessSupervisor", FakeSupervisor)
    yield FakeSupervisor


@pytest.fixture(autouse=True)
def superlink_listens_at_once(monkeypatch):
    """The fake supervisor opens no port; `_wait_until_listening` has its own tests below."""
    ports = []
    monkeypatch.setattr(FlowerRunLifecycle, "_wait_until_listening",
                        lambda self, port, timeout=None: ports.append(port))
    return ports


@pytest.fixture(autouse=True)
def model_dir(monkeypatch, tmp_path):
    directory = tmp_path / "model"
    monkeypatch.setattr(lifecycle_module.system_settings, "model_dir", str(directory))
    return directory


@pytest.fixture(autouse=True)
def fake_federation_config(monkeypatch):
    calls = []
    monkeypatch.setattr(lifecycle_module, "ensure_local_federation",
                         lambda port, ca_certfile=None: (calls.append(ca_certfile), "flnet-local")[1])
    return calls


def test_run_as_aggregator_starts_superlink_insecure_without_supernode_auth_by_default():
    """--enable-supernode-auth requires TLS, so it stays off without it - confirmed Flower
    itself refuses to start (exit code 104) with --insecure and --enable-supernode-auth set."""
    lc = FlowerRunLifecycle(FlowerApp(app_dir="flower_app"), cli=Mock())
    lc.cli.run.return_value = "123"
    lc.cli.list_run.return_value = {"status": "finished:completed"}

    success, error = lc.run_as_aggregator(port=9000)

    assert success is True
    assert error is None
    supervisor = FakeSupervisor.instances[0]
    assert supervisor.binary == "flower-superlink"
    assert supervisor.args == ["--insecure", "--host", "0.0.0.0", "--port", "9000"]
    assert supervisor.started
    assert supervisor.stopped


def test_run_as_aggregator_uses_tls_flags_when_all_three_cert_paths_are_given(fake_federation_config):
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc.cli.run.return_value = "1"
    lc.cli.list_run.return_value = {"status": "finished:completed"}

    lc.run_as_aggregator(
        port=9000,
        ssl_certfile=Path("/certs/server.pem"),
        ssl_keyfile=Path("/certs/server.key"),
        ssl_ca_certfile=Path("/certs/ca.crt"),
    )

    supervisor = FakeSupervisor.instances[0]
    assert supervisor.args == [
        "--ssl-certfile", "/certs/server.pem",
        "--ssl-keyfile", "/certs/server.key",
        "--ssl-ca-certfile", "/certs/ca.crt",
        "--host", "0.0.0.0", "--port", "9000",
        # With TLS, only registered SuperNodes may connect (Task 5).
        "--enable-supernode-auth",
    ]
    # The loopback flwr run/list control calls need root-certificates too once TLS is enabled -
    # confirmed empirically (see federation_config.py's module docstring).
    assert fake_federation_config == [Path("/certs/ca.crt")]


def test_run_as_aggregator_falls_back_to_insecure_when_only_some_cert_paths_are_given(fake_federation_config):
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc.cli.run.return_value = "1"
    lc.cli.list_run.return_value = {"status": "finished:completed"}

    lc.run_as_aggregator(ssl_certfile=Path("/certs/server.pem"))

    default_port = str(lifecycle_module.DEFAULT_SUPERLINK_PORT)
    assert FakeSupervisor.instances[0].args == ["--insecure", "--host", "0.0.0.0", "--port", default_port]
    assert fake_federation_config == [None]


def test_run_as_aggregator_can_enable_supernode_auth_once_tls_is_available():
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc.cli.run.return_value = "1"
    lc.cli.list_run.return_value = {"status": "finished:completed"}

    lc.run_as_aggregator(enable_supernode_auth=True)

    assert "--enable-supernode-auth" in FakeSupervisor.instances[0].args


def test_run_as_aggregator_calls_report_running_once_the_superlink_is_up():
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc.cli.run.return_value = "1"
    lc.cli.list_run.return_value = {"status": "finished:completed"}
    report_running = Mock()

    lc.run_as_aggregator(report_running=report_running)

    report_running.assert_called_once()


def test_run_as_aggregator_submits_the_run_and_polls_until_finished(monkeypatch):
    monkeypatch.setattr(lifecycle_module.time, "sleep", Mock())
    lc = FlowerRunLifecycle(FlowerApp(app_dir="flower_app"), cli=Mock())
    lc.cli.run.return_value = "777"
    lc.cli.list_run.side_effect = [
        {"status": "running"},
        {"status": "running"},
        {"status": "finished:completed"},
    ]

    success, error = lc.run_as_aggregator(poll_interval=0.0)

    assert success is True
    assert error is None
    lc.cli.run.assert_called_once_with(Path("flower_app"), "flnet-local")
    assert lc.cli.list_run.call_args_list == [call("flnet-local", "777")] * 3


def test_run_as_aggregator_reports_failure_with_the_status_details():
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc.cli.run.return_value = "1"
    lc.cli.list_run.return_value = {"status": "finished:failed", "status-details": "No heartbeat received"}

    success, error = lc.run_as_aggregator()

    assert success is False
    assert error == "No heartbeat received"


def test_run_as_aggregator_treats_finished_stopped_as_failure():
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc.cli.run.return_value = "1"
    lc.cli.list_run.return_value = {"status": "finished:stopped"}

    success, error = lc.run_as_aggregator()

    assert success is False
    assert error == "finished:stopped"


def test_run_as_aggregator_stops_the_superlink_even_when_flwr_run_raises():
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc.cli.run.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        lc.run_as_aggregator()

    assert FakeSupervisor.instances[0].stopped


def test_run_as_aggregator_fails_fast_if_the_superlink_process_dies_mid_poll(monkeypatch):
    monkeypatch.setattr(lifecycle_module.time, "sleep", Mock())
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc.cli.run.return_value = "1"
    lc.cli.list_run.return_value = {"status": "running"}

    def kill_after_first_check():
        FakeSupervisor.instances[0].alive = False

    lc.cli.list_run.side_effect = lambda *a, **k: (kill_after_first_check(), {"status": "running"})[1]

    success, error = lc.run_as_aggregator()

    assert success is False
    assert "exited with code 1" in error


def test_start_as_client_uses_insecure_when_no_root_certificates_given():
    lc = FlowerRunLifecycle(FlowerApp())

    lc.start_as_client(superlink_address="superlink.example:9092")

    supervisor = FakeSupervisor.instances[0]
    assert supervisor.binary == "flower-supernode"
    assert supervisor.args == ["--superlink", "superlink.example:9092", "--insecure"]
    assert supervisor.started


def test_start_as_client_with_tls_auth_and_node_config():
    lc = FlowerRunLifecycle(FlowerApp())

    lc.start_as_client(
        superlink_address="superlink.example:9092",
        root_certificates=Path("/certs/ca.crt"),
        auth_private_key=Path("/keys/supernode.key"),
        node_config={"partition-id": "0", "num-partitions": "2"},
    )

    supervisor = FakeSupervisor.instances[0]
    assert supervisor.args == [
        "--superlink", "superlink.example:9092",
        "--root-certificates", "/certs/ca.crt",
        "--auth-supernode-private-key", "/keys/supernode.key",
        "--node-config", 'partition-id="0" num-partitions="2"',
    ]


def test_is_alive_reflects_the_supervised_process():
    lc = FlowerRunLifecycle(FlowerApp())
    assert lc.is_alive() is False

    lc.start_as_client(superlink_address="x:1")
    assert lc.is_alive() is True

    lc.stop()
    assert lc.is_alive() is False


def _running_aggregator(cli, *, tls=True):
    """A lifecycle whose SuperLink is up: run_as_aggregator blocks in list_run until released."""
    lc = FlowerRunLifecycle(FlowerApp(), cli=cli)
    cli.run.return_value = "1"
    release = threading.Event()
    up = threading.Event()

    def list_run(federation, run_id):
        up.set()
        release.wait(5)
        return {"status": "finished:completed"}

    cli.list_run.side_effect = list_run
    kwargs = dict(ssl_certfile=Path("/c/s.pem"), ssl_keyfile=Path("/c/s.key"),
                  ssl_ca_certfile=Path("/c/ca.crt")) if tls else {}
    thread = threading.Thread(target=lc.run_as_aggregator, kwargs=kwargs, daemon=True)
    thread.start()
    assert up.wait(5)
    return lc, release, thread


def test_register_supernode_before_the_superlink_is_up_raises_so_the_clinic_retries():
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())

    with pytest.raises(FlowerCliError, match="not running yet"):
        lc.register_supernode("ecdsa-sha2-nistp384 AAAA")


def test_register_supernode_registers_the_key_once_even_when_asked_again():
    cli = Mock()
    cli.supernode_register.return_value = "42"
    lc, release, thread = _running_aggregator(cli)

    lc.register_supernode("ecdsa-sha2-nistp384 AAAA", name="clinic-1")
    lc.register_supernode("ecdsa-sha2-nistp384 AAAA", name="clinic-1")

    cli.supernode_register.assert_called_once()
    key_file, federation = cli.supernode_register.call_args.args
    assert federation == "flnet-local"
    assert cli.supernode_register.call_args.kwargs == {"name": "clinic-1"}
    assert not key_file.exists()  # the temporary key file is cleaned up
    release.set()
    thread.join(5)


def test_register_supernode_treats_an_already_registered_key_as_success():
    cli = Mock()
    cli.supernode_register.side_effect = FlowerCliError(
        "flwr supernode register failed: [code: 23] Public key already in use.")
    lc, release, thread = _running_aggregator(cli)

    lc.register_supernode("ecdsa-sha2-nistp384 AAAA")

    release.set()
    thread.join(5)


def test_register_supernode_is_a_no_op_while_running_without_supernode_auth():
    cli = Mock()
    lc, release, thread = _running_aggregator(cli, tls=False)

    lc.register_supernode("ecdsa-sha2-nistp384 AAAA")

    cli.supernode_register.assert_not_called()
    release.set()
    thread.join(5)


def test_register_supernode_after_the_run_ended_raises():
    cli = Mock()
    lc, release, thread = _running_aggregator(cli)
    release.set()
    thread.join(5)

    with pytest.raises(FlowerCliError):
        lc.register_supernode("ecdsa-sha2-nistp384 AAAA")


# --- Model-save confirmation (#11 Task 6) ---

def _completing_run(lc, *, saves=None):
    """Makes the fake run complete; `saves` writes files into the model dir while it "runs"."""
    lc.cli.run.return_value = "1"

    def list_run(federation, run_id):
        if saves:
            saves()
        return {"status": "finished:completed"}
    lc.cli.list_run.side_effect = list_run


def test_run_as_aggregator_starts_the_superlink_in_the_model_dir_with_model_dir_set(model_dir):
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    _completing_run(lc)

    lc.run_as_aggregator()

    supervisor = FakeSupervisor.instances[0]
    assert supervisor.cwd == model_dir.resolve()
    assert supervisor.extra_env == {"MODEL_DIR": str(model_dir.resolve())}
    assert model_dir.is_dir()


def test_run_as_aggregator_succeeds_with_the_model_the_server_app_saved(model_dir):
    lc = FlowerRunLifecycle(FlowerApp(model_file="final_model.npz"), cli=Mock())
    _completing_run(lc, saves=lambda: (model_dir / "final_model.npz").write_bytes(b"weights"))

    success, error = lc.run_as_aggregator()

    assert (success, error) == (True, None)
    assert lc.saved_model_path() == model_dir.resolve() / "final_model.npz"


def test_run_as_aggregator_fails_a_completed_run_that_saved_no_model(model_dir):
    lc = FlowerRunLifecycle(FlowerApp(model_file="final_model.npz"), cli=Mock())
    _completing_run(lc)

    success, error = lc.run_as_aggregator()

    assert success is False
    assert "saved no model" in error and "final_model.npz" in error
    assert lc.saved_model_path() is None


def test_run_as_aggregator_does_not_take_a_model_left_over_from_an_earlier_run(model_dir):
    import os
    model_dir.mkdir(parents=True)
    stale = model_dir / "final_model.npz"
    stale.write_bytes(b"old weights")
    os.utime(stale, (1_000_000, 1_000_000))
    lc = FlowerRunLifecycle(FlowerApp(model_file="final_model.npz"), cli=Mock())
    _completing_run(lc)

    success, error = lc.run_as_aggregator()

    assert success is False
    assert "earlier run" in error


def test_run_as_aggregator_without_a_declared_model_file_checks_nothing():
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    _completing_run(lc)

    assert lc.run_as_aggregator() == (True, None)
    assert lc.saved_model_path() is None


def test_a_failed_run_is_not_checked_for_a_model(model_dir):
    lc = FlowerRunLifecycle(FlowerApp(model_file="final_model.npz"), cli=Mock())
    lc.cli.run.return_value = "1"
    lc.cli.list_run.return_value = {"status": "finished:failed", "status-details": "boom"}

    assert lc.run_as_aggregator() == (False, "boom")


@pytest.mark.parametrize("bad", ["", "/abs/model.npz", "../model.npz", "sub/../../model.npz"])
def test_flower_app_rejects_a_model_file_outside_the_model_dir(bad):
    with pytest.raises(ValueError):
        FlowerApp(model_file=bad)


# --- Waiting for the SuperLink before `flwr run` ---

def test_run_as_aggregator_waits_for_the_superlink_port_before_flwr_run(superlink_listens_at_once):
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc.cli.run.side_effect = lambda *a, **k: (superlink_listens_at_once.append("flwr run"), "1")[1]
    lc.cli.list_run.return_value = {"status": "finished:completed"}

    lc.run_as_aggregator(port=9000)

    assert superlink_listens_at_once == [9000, "flwr run"]


def test_run_as_aggregator_returns_a_flwr_cli_error_as_a_failed_run():
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc.cli.run.side_effect = FlowerCliError("flwr run failed: no such app")

    assert lc.run_as_aggregator() == (False, "flwr run failed: no such app")
    assert FakeSupervisor.instances[0].stopped


def _lifecycle_with(supervisor):
    lc = FlowerRunLifecycle(FlowerApp(), cli=Mock())
    lc._supervisor = supervisor
    return lc


def test_wait_until_listening_returns_once_the_port_accepts_connections(monkeypatch):
    import socket
    monkeypatch.undo()  # the real method, not the autouse stub
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    try:
        _lifecycle_with(FakeSupervisor("flower-superlink", []))._wait_until_listening(
            server.getsockname()[1], timeout=5)
    finally:
        server.close()


def _free_port():
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_wait_until_listening_fails_fast_once_the_superlink_died(monkeypatch):
    monkeypatch.undo()
    supervisor = FakeSupervisor("flower-superlink", [])
    supervisor.alive = False

    with pytest.raises(FlowerProcessError, match="exited"):
        _lifecycle_with(supervisor)._wait_until_listening(_free_port(), timeout=30)


def test_wait_until_listening_gives_up_after_the_timeout(monkeypatch):
    monkeypatch.undo()

    with pytest.raises(FlowerProcessError, match="did not accept connections"):
        _lifecycle_with(FakeSupervisor("flower-superlink", []))._wait_until_listening(
            _free_port(), timeout=0.5)

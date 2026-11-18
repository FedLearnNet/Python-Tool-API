from pathlib import Path
from unittest.mock import Mock, call

import pytest

from pyfedappwrap.engine.service.flower import lifecycle as lifecycle_module
from pyfedappwrap.engine.service.flower.lifecycle import FlowerRunLifecycle
from pyfedappwrap.engine.service.flower.process import FlowerProcessError
from pyfedappwrap.learning.federated.flower_app import FlowerApp


class FakeSupervisor:
    """Stands in for FlowerProcessSupervisor so these tests exercise lifecycle's own
    orchestration logic without starting real OS processes."""

    instances: list["FakeSupervisor"] = []

    def __init__(self, binary, args):
        self.binary = binary
        self.args = args
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
def fake_federation_config(monkeypatch):
    monkeypatch.setattr(lifecycle_module, "ensure_local_federation", lambda port: "flnet-local")


def test_run_as_aggregator_starts_superlink_insecure_without_supernode_auth_by_default():
    """--enable-supernode-auth requires TLS, which this still runs without (see
    Flower_Integration_Plan.md's flagged TLS gap) - confirmed Flower itself refuses to start
    (exit code 104) with --insecure and --enable-supernode-auth both set."""
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

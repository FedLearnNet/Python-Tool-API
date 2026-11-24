import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from pyfedappwrap.engine.service.flower.cli import (
    FlowerCli,
    FlowerCliError,
    is_already_registered,
    status_is_finished,
    status_is_successful,
)


def completed(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_returns_the_run_id_as_a_string_even_when_flower_sends_a_json_number(monkeypatch):
    cli = FlowerCli()
    run_call = Mock(return_value=completed(json.dumps({"success": True, "run-id": 12345})))
    monkeypatch.setattr(subprocess, "run", run_call)

    run_id = cli.run(Path("flower_app"), "flnet-local")

    assert run_id == "12345"
    assert run_call.call_args.args[0] == ["flwr", "run", "flower_app", "flnet-local", "--format", "json"]


def test_run_raises_with_the_error_message_on_failure(monkeypatch):
    cli = FlowerCli()
    monkeypatch.setattr(subprocess, "run",
                        Mock(return_value=completed(json.dumps({"success": False, "error-message": "boom"}))))

    with pytest.raises(FlowerCliError, match="boom"):
        cli.run(Path("flower_app"), "flnet-local")


def test_list_run_takes_no_app_argument_and_finds_the_matching_run(monkeypatch):
    cli = FlowerCli()
    response = {"success": True, "runs": [
        {"run-id": "1", "status": "running"},
        {"run-id": "42", "status": "finished:completed"},
    ]}
    run_call = Mock(return_value=completed(json.dumps(response)))
    monkeypatch.setattr(subprocess, "run", run_call)

    result = cli.list_run("flnet-local", "42")

    assert result == {"run-id": "42", "status": "finished:completed"}
    assert run_call.call_args.args[0] == ["flwr", "list", "flnet-local", "--run-id", "42", "--format", "json"]


def test_list_run_raises_when_no_run_matches(monkeypatch):
    cli = FlowerCli()
    monkeypatch.setattr(subprocess, "run",
                        Mock(return_value=completed(json.dumps({"success": True, "runs": []}))))

    with pytest.raises(FlowerCliError, match="42"):
        cli.list_run("flnet-local", "42")


def test_stop_puts_run_id_before_the_superlink_name(monkeypatch):
    cli = FlowerCli()
    run_call = Mock(return_value=completed(json.dumps({"success": True})))
    monkeypatch.setattr(subprocess, "run", run_call)

    cli.stop("flnet-local", "42")

    assert run_call.call_args.args[0] == ["flwr", "stop", "42", "flnet-local", "--format", "json"]


def test_raises_on_non_json_output(monkeypatch):
    cli = FlowerCli()
    monkeypatch.setattr(subprocess, "run", Mock(return_value=completed("not json")))

    with pytest.raises(FlowerCliError, match="non-JSON"):
        cli.run(Path("flower_app"), "flnet-local")


def test_raises_on_empty_output(monkeypatch):
    cli = FlowerCli()
    monkeypatch.setattr(subprocess, "run", Mock(return_value=completed("", returncode=1, stderr="crashed")))

    with pytest.raises(FlowerCliError, match="crashed"):
        cli.run(Path("flower_app"), "flnet-local")


def test_raises_on_timeout(monkeypatch):
    cli = FlowerCli(timeout=1.0)
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired(cmd="flwr", timeout=1.0)))

    with pytest.raises(FlowerCliError, match="timed out"):
        cli.run(Path("flower_app"), "flnet-local")


@pytest.mark.parametrize("status,expected", [
    ("running", False),
    ("finished:completed", True),
    ("finished:stopped", True),
    ("finished:failed", True),
    (None, False),
])
def test_status_is_finished(status, expected):
    assert status_is_finished(status) is expected


@pytest.mark.parametrize("status,expected", [
    ("finished:completed", True),
    ("finished:stopped", False),
    ("finished:failed", False),
    ("running", False),
])
def test_status_is_successful(status, expected):
    assert status_is_successful(status) is expected


def test_supernode_register_returns_the_node_id_flower_assigned(monkeypatch):
    """Output shape confirmed against a real Flower 1.43 SuperLink with --enable-supernode-auth."""
    cli = FlowerCli()
    run_call = Mock(return_value=completed(json.dumps({"success": True, "node-id": 17376333687335559091})))
    monkeypatch.setattr(subprocess, "run", run_call)

    node_id = cli.supernode_register(Path("key.pub"), "flnet-local", name="clinic-1")

    assert node_id == "17376333687335559091"
    assert run_call.call_args.args[0] == [
        "flwr", "supernode", "register", "key.pub", "flnet-local", "--format", "json",
        "--name", "clinic-1",
    ]


def test_supernode_register_failure_for_an_already_registered_key_is_recognizable(monkeypatch):
    cli = FlowerCli()
    monkeypatch.setattr(subprocess, "run", Mock(return_value=completed(json.dumps({
        "success": False,
        "error-message": "Using SuperLink: t (127.0.0.1:18000)\n\n[code: 23] Public key already in use.",
    }))))

    with pytest.raises(FlowerCliError) as raised:
        cli.supernode_register(Path("key.pub"), "flnet-local")

    assert is_already_registered(raised.value)


def test_supernode_register_other_failures_are_not_mistaken_for_already_registered(monkeypatch):
    cli = FlowerCli()
    monkeypatch.setattr(subprocess, "run", Mock(return_value=completed(json.dumps({
        "success": False, "error-message": "Connection to the SuperLink is unavailable.",
    }))))

    with pytest.raises(FlowerCliError) as raised:
        cli.supernode_register(Path("key.pub"), "flnet-local")

    assert not is_already_registered(raised.value)

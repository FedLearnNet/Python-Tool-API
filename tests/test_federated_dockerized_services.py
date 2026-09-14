from pathlib import Path
import logging

from pyfedappwrap.engine.tests.federated import dockerized_services


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_ensure_dockerized_services_skips_docker_when_services_are_healthy(monkeypatch):
    calls: list[list[str]] = []

    def fake_get(url: str, timeout: float):
        return FakeResponse(200)

    def fake_run(command, **kwargs):
        calls.append(command)

    monkeypatch.setattr(dockerized_services.http_requests, "get", fake_get)
    monkeypatch.setattr(dockerized_services.subprocess, "run", fake_run)

    dockerized_services.ensure_dockerized_federated_services(
        relay_url="http://relay",
        controller_orch_url="http://controller",
        startup_timeout_seconds=0.1,
    )

    assert calls == []


def test_ensure_dockerized_services_starts_compose_when_services_are_missing(monkeypatch, tmp_path, caplog):
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text("services: {}\n")
    health_attempts = {"count": 0}
    commands: list[list[str]] = []

    def fake_get(url: str, timeout: float):
        health_attempts["count"] += 1
        if health_attempts["count"] <= 2:
            raise dockerized_services.http_requests.ConnectionError("not yet")
        return FakeResponse(200)

    def fake_run(command, **kwargs):
        commands.append(command)

    monkeypatch.setenv(dockerized_services.COMPOSE_ENV_VAR, str(compose_file))
    monkeypatch.setattr(dockerized_services.http_requests, "get", fake_get)
    monkeypatch.setattr(dockerized_services.subprocess, "run", fake_run)

    caplog.set_level(logging.INFO, logger=dockerized_services.__name__)
    dockerized_services.ensure_dockerized_federated_services(
        relay_url="http://relay",
        controller_orch_url="http://controller",
        startup_timeout_seconds=1.0,
        poll_interval_seconds=0.01,
    )

    assert commands == [
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
    ]
    assert "Checking dockerized federated services" in caplog.text
    assert "starting compose file" in caplog.text
    assert "Dockerized federated services became healthy" in caplog.text


def test_packaged_docker_compose_file_is_discoverable():
    with dockerized_services.federated_docker_compose_file() as compose_file:
        assert Path(compose_file).name == dockerized_services.COMPOSE_FILENAME
        assert Path(compose_file).is_file()

"""Utilities for ensuring dockerized federated test services are available."""
from __future__ import annotations

from contextlib import contextmanager
from importlib import resources
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Iterator

import requests as http_requests


COMPOSE_FILENAME = "fed-learn-sim-docker-compose.yml"
COMPOSE_ENV_VAR = "PYFEDAPPWRAP_FEDERATED_DOCKER_COMPOSE"
logger = logging.getLogger(__name__)


def ensure_dockerized_federated_services(
        *,
        relay_url: str,
        controller_orch_url: str,
        startup_timeout_seconds: float = 90.0,
        health_timeout_seconds: float = 3.0,
        poll_interval_seconds: float = 1.0,
) -> None:
    """Start the dockerized controller and relay if they are not already healthy."""
    logger.info(
        "Checking dockerized federated services: relay=%s controller_orch=%s",
        relay_url,
        controller_orch_url,
    )
    if dockerized_federated_services_are_healthy(
            relay_url=relay_url,
            controller_orch_url=controller_orch_url,
            timeout_seconds=health_timeout_seconds,
    ):
        logger.info("Dockerized federated services are already healthy; skipping docker compose up.")
        return

    with federated_docker_compose_file() as compose_file:
        logger.info("Dockerized federated services are not healthy; starting compose file %s", compose_file)
        _docker_compose_up(compose_file)
        deadline = time.monotonic() + startup_timeout_seconds
        while time.monotonic() < deadline:
            if dockerized_federated_services_are_healthy(
                    relay_url=relay_url,
                    controller_orch_url=controller_orch_url,
                    timeout_seconds=health_timeout_seconds,
            ):
                logger.info("Dockerized federated services became healthy.")
                return
            time.sleep(poll_interval_seconds)

    raise RuntimeError(
        "Federated dockerized controller and relay did not become healthy in time. "
        "Check Docker, container logs, and configured federated test service URLs."
    )


def dockerized_federated_services_are_healthy(
        *,
        relay_url: str,
        controller_orch_url: str,
        timeout_seconds: float = 3.0,
) -> bool:
    return (
        _service_is_healthy(relay_url, timeout_seconds=timeout_seconds)
        and _service_is_healthy(controller_orch_url, timeout_seconds=timeout_seconds)
    )


@contextmanager
def federated_docker_compose_file() -> Iterator[Path]:
    """Yield a compose file path from env, checkout, or package resources."""
    env_path = os.getenv(COMPOSE_ENV_VAR)
    if env_path:
        compose_path = Path(env_path).expanduser()
        if not compose_path.is_file():
            raise RuntimeError(
                f"{COMPOSE_ENV_VAR} points to {str(compose_path)!r}, but that file does not exist."
            )
        logger.info("Using federated docker compose file from %s: %s", COMPOSE_ENV_VAR, compose_path)
        yield compose_path
        return

    for compose_path in _local_compose_candidates():
        if compose_path.is_file():
            logger.info("Using federated docker compose file from local checkout: %s", compose_path)
            yield compose_path
            return

    package_resource = resources.files(__package__).joinpath(COMPOSE_FILENAME)
    if package_resource.is_file():
        with resources.as_file(package_resource) as compose_path:
            logger.info("Using packaged federated docker compose file: %s", compose_path)
            yield compose_path
            return

    raise RuntimeError(
        f"Could not find {COMPOSE_FILENAME!r}. Install pyfedappwrap with package data, "
        f"run from a source checkout, or set {COMPOSE_ENV_VAR}."
    )


def _local_compose_candidates() -> Iterator[Path]:
    cwd = Path.cwd()
    yield cwd / COMPOSE_FILENAME
    for parent in Path(__file__).resolve().parents:
        yield parent / COMPOSE_FILENAME


def _service_is_healthy(base_url: str, *, timeout_seconds: float) -> bool:
    try:
        response = http_requests.get(
            f"{base_url.rstrip('/')}/healthz",
            timeout=timeout_seconds,
        )
        healthy = response.status_code == 200
        logger.info(
            "Federated service health check %s/healthz -> HTTP %s healthy=%s",
            base_url.rstrip("/"),
            response.status_code,
            healthy,
        )
        return healthy
    except http_requests.RequestException as exc:
        logger.info("Federated service health check %s/healthz failed: %s", base_url.rstrip("/"), exc)
        return False


def _docker_compose_up(compose_file: Path) -> None:
    try:
        logger.info("Running docker compose for federated services: docker compose -f %s up -d", compose_file)
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("docker compose up for federated services completed.")
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise RuntimeError(
            "Could not start dockerized federated controller and relay with "
            f"{str(compose_file)!r}. Make sure Docker is running and the compose "
            f"images are available. {stderr}".strip()
        ) from exc

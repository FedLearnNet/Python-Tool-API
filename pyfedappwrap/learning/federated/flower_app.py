"""The Flower App bundle a tool registers with the engine.

This is a thin descriptor, not an executable app: the actual `ClientApp`/`ServerApp` code lives
in `app_dir` (a normal Flower App bundle, with its own `pyproject.toml`), and the SuperLink/
SuperNode process lifecycle lives in the engine (see `pyfedappwrap.engine.service.flower`),
started when a federated run for this tool begins - the same split `BaseFederatedApp` has from
`FederatedWorkerManager` for FL-Net's own protocol.
"""
from __future__ import annotations

from pathlib import Path


class FlowerApp:
    def __init__(self, app_dir: str = "flower_app"):
        self.app_dir = Path(app_dir)

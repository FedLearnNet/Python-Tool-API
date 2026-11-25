"""The Flower App bundle a tool registers with the engine.

This is a thin descriptor, not an executable app: the actual `ClientApp`/`ServerApp` code lives
in `app_dir` (a normal Flower App bundle, with its own `pyproject.toml`), and the SuperLink/
SuperNode process lifecycle lives in the engine (see `pyfedappwrap.engine.service.flower`),
started when a federated run for this tool begins - the same split `BaseFederatedApp` has from
`FederatedWorkerManager` for FL-Net's own protocol.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


class FlowerApp:
    def __init__(self, app_dir: str = "flower_app", *, model_file: Optional[str] = None):
        """`model_file` is the file name the `ServerApp` saves the final model under, inside
        the model directory: `os.environ["MODEL_DIR"]` while it runs (the SuperLink, and so the
        `ServerApp` it spawns, also starts with that directory as its working directory, so a
        bare relative name lands there too). The engine only reports the platform's run as
        finished once that file was written during the run, and uploads it as the step's
        model. `None` means the app produces no model, and nothing is checked or uploaded."""
        self.app_dir = Path(app_dir)
        if model_file is not None and (not model_file or Path(model_file).is_absolute()
                                       or ".." in Path(model_file).parts):
            raise ValueError(f"model_file must be a file name inside MODEL_DIR, got {model_file!r}")
        self.model_file = model_file

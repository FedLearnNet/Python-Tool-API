"""Thin wrapper around the `flwr` CLI's `run`/`list`/`stop` subcommands.

Confirmed empirically (set up a real local SuperLink + two SuperNodes and ran the actual CLI
against them, Flower 1.43.0 - see `Flower_Integration_Plan.md`'s "Empirically verified" section)
that `--format json` is a stable, documented, machine-readable contract - this module always
uses it and never parses free-text/table output.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Optional


class FlowerCliError(RuntimeError):
    """A `flwr` CLI invocation failed or returned a response this code can't use."""


class FlowerCli:
    def __init__(self, *, binary: str = "flwr", timeout: float = 60.0):
        self.binary = binary
        self.timeout = timeout

    def run(self, app_dir: Path, federation: str) -> str:
        """Submits a run; returns its run-id. `flwr run`'s own `--format json` schema (confirmed
        on 1.43.0) is `{"success": bool, "run-id": ..., ...}` on success, or
        `{"success": false, "error-message": "..."}` on failure - `run-id` has been observed as
        both a JSON number (1.23.0) and a JSON string (1.43.0), so this always returns it as a
        plain string regardless of which the installed version sends."""
        response = self._invoke(["run", str(app_dir), federation, "--format", "json"])
        if not response.get("success"):
            raise FlowerCliError(f"flwr run failed: {response.get('error-message', response)}")
        run_id = response.get("run-id")
        if run_id is None:
            raise FlowerCliError(f"flwr run reported success without a run-id: {response}")
        return str(run_id)

    def list_run(self, federation: str, run_id: str) -> dict[str, Any]:
        """Returns the one run's status dict, e.g. {"status": "running" | "finished:completed" |
        "finished:stopped" | ..., "status-details": ..., "elapsed": ..., ...} (exact optional
        fields vary by Flower version - callers should only rely on "status" being present).
        `flwr list` takes no APP argument - confirmed on 1.43.0 (`flwr list [SUPERLINK]`), unlike
        `run`, which still does."""
        response = self._invoke(["list", federation, "--run-id", run_id, "--format", "json"])
        if not response.get("success"):
            raise FlowerCliError(f"flwr list failed: {response.get('error-message', response)}")
        runs = response.get("runs") or []
        matching = [r for r in runs if str(r.get("run-id")) == run_id]
        if not matching:
            raise FlowerCliError(f"flwr list returned no run matching run-id {run_id}: {response}")
        return matching[0]

    def stop(self, federation: str, run_id: str) -> None:
        """`flwr stop RUN_ID [SUPERLINK]` - run_id comes first, and (like `list`) there's no APP
        argument at all, confirmed on 1.43.0."""
        response = self._invoke(["stop", run_id, federation, "--format", "json"])
        if not response.get("success"):
            raise FlowerCliError(f"flwr stop failed: {response.get('error-message', response)}")

    def _invoke(self, args: list[str]) -> dict[str, Any]:
        command = [self.binary, *args]
        logging.info("Running: %s", " ".join(command))
        try:
            result = subprocess.run(  # noqa: S603 - args are our own config, not user input
                command, capture_output=True, text=True, timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise FlowerCliError(f"{' '.join(command)} timed out after {self.timeout}s") from exc
        output = result.stdout.strip()
        if not output:
            raise FlowerCliError(
                f"{' '.join(command)} produced no output (exit {result.returncode}): {result.stderr.strip()}"
            )
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise FlowerCliError(f"{' '.join(command)} returned non-JSON output: {output}") from exc


def status_is_finished(status: Optional[str]) -> bool:
    return bool(status) and status.startswith("finished:")


def status_is_successful(status: Optional[str]) -> bool:
    return status == "finished:completed"

"""Drives one Flower-tagged federated run: starts the right OS process for this attempt's role
(SuperLink for the platform's own aggregator attempt, SuperNode for a clinic's participant
attempt - the same AGGREGATOR/CLIENT distinction FL-Net's own path already uses), and for the
aggregator, drives `flwr run`/`flwr list` to completion and reports status back through the
`FederatedStatusReporter`.

The client (SuperNode) side intentionally does *not* poll `flwr list` at all: a SuperNode has no
API to ask "is my current run done", and in this architecture it doesn't need one - the
orchestrator (Learning APIs) already ends every attempt of a step explicitly when the whole run
finishes, the same way it already does for every other attempt type - see
`FederatedWorkerManager._start_federated_run_flnet` for that existing path's own equivalent.
"""
from __future__ import annotations

import logging
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.service.flower.cli import (
    FlowerCli,
    FlowerCliError,
    is_already_registered,
    status_is_finished,
    status_is_successful,
)
from pyfedappwrap.engine.service.flower.federation_config import ensure_local_federation
from pyfedappwrap.engine.service.flower.process import FlowerProcessError, FlowerProcessSupervisor
from pyfedappwrap.learning.federated.flower_app import FlowerApp

DEFAULT_SUPERLINK_PORT = 8000
DEFAULT_POLL_INTERVAL_SECONDS = 3.0
# How long a freshly started SuperLink may take to accept connections.
SUPERLINK_STARTUP_TIMEOUT_SECONDS = 60.0


class FlowerRunLifecycle:
    def __init__(self, flower_app: FlowerApp, *, cli: Optional[FlowerCli] = None):
        self.flower_app = flower_app
        self.cli = cli or FlowerCli()
        self._supervisor: Optional[FlowerProcessSupervisor] = None
        # Aggregator only: set once the SuperLink is up and the local federation entry points at
        # it, so `register_supernode` (called from the websocket thread) knows it can reach it.
        self._federation: Optional[str] = None
        self._supernode_auth = False
        self._registered_keys: set[str] = set()
        self._register_lock = threading.Lock()
        self._saved_model_path: Optional[Path] = None

    def run_as_aggregator(
            self,
            *,
            port: int = DEFAULT_SUPERLINK_PORT,
            enable_supernode_auth: Optional[bool] = None,
            ssl_certfile: Optional[Path] = None,
            ssl_keyfile: Optional[Path] = None,
            ssl_ca_certfile: Optional[Path] = None,
            poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
            report_running: Optional[callable] = None,
    ) -> tuple[bool, Optional[str]]:
        """Starts the SuperLink, submits the run, polls until Flower reports it finished.
        Returns (success, error_message). Blocks the calling thread until the run is done or the
        SuperLink process dies - callers run this on their own worker thread, same as FL-Net's
        own `_run_federated`.

        A run Flower reports as `finished:completed` still only counts as a success if the app's
        declared `model_file` was written during it (see `FlowerApp`); `saved_model_path()`
        then gives its path.

        Runs `--insecure` unless all three of `ssl_certfile`/`ssl_keyfile`/`ssl_ca_certfile` are
        given. `enable_supernode_auth` defaults to "on exactly when TLS is": with it, only
        SuperNodes registered through `register_supernode` may connect (Task 5). It can't be on
        without TLS - Flower refuses to start ("the flag requires encrypted TLS
        communications", exit code 104, confirmed by actually starting a SuperLink with both)."""
        tls_enabled = bool(ssl_certfile and ssl_keyfile and ssl_ca_certfile)
        if enable_supernode_auth is None:
            enable_supernode_auth = tls_enabled
        if tls_enabled:
            args = ["--ssl-certfile", str(ssl_certfile), "--ssl-keyfile", str(ssl_keyfile),
                    "--ssl-ca-certfile", str(ssl_ca_certfile),
                    "--host", "0.0.0.0", "--port", str(port)]
        else:
            args = ["--insecure", "--host", "0.0.0.0", "--port", str(port)]
        if enable_supernode_auth:
            args.append("--enable-supernode-auth")
        model_dir = Path(system_settings.model_dir).resolve()
        model_dir.mkdir(parents=True, exist_ok=True)
        self._saved_model_path = None
        # The ServerApp runs in a process the SuperLink spawns, so it inherits both: MODEL_DIR to
        # save against explicitly, and the working directory for a bare relative file name (which
        # otherwise lands wherever the engine happened to start - Flower_Integration_Plan.md).
        self._supervisor = FlowerProcessSupervisor(
            "flower-superlink", args, cwd=model_dir, extra_env={"MODEL_DIR": str(model_dir)})
        started_at = time.time()
        self._supervisor.start()
        try:
            # `flwr run` right after the start fails with "Connection to the SuperLink is
            # unavailable" - it doesn't wait for the SuperLink itself (seen with real 1.43).
            self._wait_until_listening(port)
            federation = ensure_local_federation(
                port, ca_certfile=ssl_ca_certfile if tls_enabled else None)
            self._supernode_auth = enable_supernode_auth
            self._federation = federation
            if report_running:
                report_running()
            flower_run_id = self.cli.run(self.flower_app.app_dir, federation)
            logging.info("Flower run %s submitted on federation %s", flower_run_id, federation)

            status_dict = {}
            while True:
                self._supervisor.check_alive()
                status_dict = self.cli.list_run(federation, flower_run_id)
                status = status_dict.get("status")
                if status_is_finished(status):
                    break
                time.sleep(poll_interval)

            if not status_is_successful(status_dict.get("status")):
                return False, status_dict.get("status-details") or status_dict.get("status")
            return self._confirm_model_saved(model_dir, started_at)
        except (FlowerProcessError, FlowerCliError) as exc:
            return False, str(exc)
        finally:
            self._federation = None
            self._supervisor.stop()

    def _wait_until_listening(
            self, port: int, timeout: float = SUPERLINK_STARTUP_TIMEOUT_SECONDS) -> None:
        deadline = time.monotonic() + timeout
        while True:
            self._supervisor.check_alive()
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                    return
            except OSError:
                if time.monotonic() >= deadline:
                    raise FlowerProcessError(
                        f"flower-superlink did not accept connections on port {port} "
                        f"within {timeout:.0f}s")
                time.sleep(0.2)

    def _confirm_model_saved(
            self, model_dir: Path, started_at: float) -> tuple[bool, Optional[str]]:
        model_file = self.flower_app.model_file
        if model_file is None:
            return True, None
        model_path = model_dir / model_file
        if not model_path.is_file():
            return False, (f"The Flower run completed, but its ServerApp saved no model at "
                           f"{model_path} (FlowerApp.model_file)")
        # A file left by an earlier run in the same directory is not this run's model. A small
        # tolerance covers filesystems that store modification times coarser than time.time().
        if os.path.getmtime(model_path) < started_at - 2.0:
            return False, (f"The Flower run completed, but {model_path} was not written during "
                           f"it - it is left over from an earlier run")
        self._saved_model_path = model_path
        return True, None

    def saved_model_path(self) -> Optional[Path]:
        """Aggregator only: the model the last successful run saved, or None if the app declares
        no `model_file` (or the run didn't succeed)."""
        return self._saved_model_path

    def register_supernode(self, public_key: str, *, name: Optional[str] = None) -> None:
        """Aggregator only: allows a clinic's SuperNode (by its OpenSSH EC public key) to connect
        to this run's SuperLink. Safe to call again for the same key - a clinic retries until it
        hears back, so a repeat just succeeds. Raises FlowerCliError while the SuperLink isn't
        up yet (the clinic retries) or when Flower refuses the key."""
        federation = self._federation
        if federation is None:
            raise FlowerCliError("The SuperLink of this run is not running yet")
        if not self._supernode_auth:
            # No allowlist to add to - any SuperNode may connect (first, insecure run).
            return
        with self._register_lock:
            if public_key in self._registered_keys:
                return
            with tempfile.NamedTemporaryFile("w", suffix=".pub", delete=False) as key_file:
                key_file.write(public_key)
            key_path = Path(key_file.name)
            try:
                node_id = self.cli.supernode_register(key_path, federation, name=name)
                logging.info("Registered SuperNode %s as node %s", name or "", node_id)
            except FlowerCliError as exc:
                if not is_already_registered(exc):
                    raise
            finally:
                key_path.unlink(missing_ok=True)
            self._registered_keys.add(public_key)

    def start_as_client(
            self,
            *,
            superlink_address: str,
            root_certificates: Optional[Path] = None,
            auth_private_key: Optional[Path] = None,
            node_config: Optional[dict[str, str]] = None,
    ) -> None:
        """Starts the SuperNode and leaves it running; does not block. `stop()` ends it. There is
        deliberately no run-completion polling here - see the module docstring."""
        args = ["--superlink", superlink_address]
        if root_certificates is not None:
            args += ["--root-certificates", str(root_certificates)]
        else:
            args.append("--insecure")
        if auth_private_key is not None:
            args += ["--auth-supernode-private-key", str(auth_private_key)]
        if node_config:
            pairs = " ".join(f'{key}="{value}"' for key, value in node_config.items())
            args += ["--node-config", pairs]
        self._supervisor = FlowerProcessSupervisor("flower-supernode", args)
        self._supervisor.start()

    def is_alive(self) -> bool:
        return self._supervisor is not None and self._supervisor.is_alive()

    def stop(self) -> None:
        if self._supervisor is not None:
            self._supervisor.stop()

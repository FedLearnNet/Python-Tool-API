"""Drives one Flower-tagged federated run: starts the right OS process for this attempt's role
(SuperLink for the platform's own aggregator attempt, SuperNode for a clinic's participant
attempt - the same AGGREGATOR/CLIENT distinction FL-Net's own path already uses), and for the
aggregator, drives `flwr run`/`flwr list` to completion and reports status back through the
same `FederatedStatusReporter` FL-Net's own path already uses - there is no separate Flower
status-relay mechanism, by design (see Flower_Integration_Plan.md's resolved #13<->#11 contract).

The client (SuperNode) side intentionally does *not* poll `flwr list` at all: a SuperNode has no
API to ask "is my current run done", and in this architecture it doesn't need one - the
orchestrator (Learning APIs) already ends every attempt of a step explicitly when the whole run
finishes, the same way it already does for every other attempt type - see
`FederatedWorkerManager._start_federated_run_flnet` for that existing path's own equivalent.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from pyfedappwrap.engine.service.flower.cli import FlowerCli, status_is_finished, status_is_successful
from pyfedappwrap.engine.service.flower.federation_config import ensure_local_federation
from pyfedappwrap.engine.service.flower.process import FlowerProcessError, FlowerProcessSupervisor
from pyfedappwrap.learning.federated.flower_app import FlowerApp

DEFAULT_SUPERLINK_PORT = 8000
DEFAULT_POLL_INTERVAL_SECONDS = 3.0


class FlowerRunLifecycle:
    def __init__(self, flower_app: FlowerApp, *, cli: Optional[FlowerCli] = None):
        self.flower_app = flower_app
        self.cli = cli or FlowerCli()
        self._supervisor: Optional[FlowerProcessSupervisor] = None

    def run_as_aggregator(
            self,
            *,
            port: int = DEFAULT_SUPERLINK_PORT,
            enable_supernode_auth: bool = True,
            poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
            report_running: Optional[callable] = None,
    ) -> tuple[bool, Optional[str]]:
        """Starts the SuperLink, submits the run, polls until Flower reports it finished.
        Returns (success, error_message). Blocks the calling thread until the run is done or the
        SuperLink process dies - callers run this on their own worker thread, same as FL-Net's
        own `_run_federated`."""
        args = ["--insecure", "--host", "0.0.0.0", "--port", str(port)]
        if enable_supernode_auth:
            args.append("--enable-supernode-auth")
        self._supervisor = FlowerProcessSupervisor("flower-superlink", args)
        self._supervisor.start()
        try:
            federation = ensure_local_federation(port)
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

            if status_is_successful(status_dict.get("status")):
                return True, None
            return False, status_dict.get("status-details") or status_dict.get("status")
        except FlowerProcessError as exc:
            return False, str(exc)
        finally:
            self._supervisor.stop()

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

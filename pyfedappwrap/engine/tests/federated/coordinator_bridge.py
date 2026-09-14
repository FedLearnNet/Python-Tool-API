from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from pyfedappwrap.engine.federated.models import FLNetDataPackageDTO, FLNetMessageMetaDTO

logger = logging.getLogger(__name__)


class CoordinatorTrainingBridge:
    """In-process handoff between a coordinator clinic's two threads: the training app and the
    aggregator.

    The coordinator runs the ordinary training app (so it trains on its own data and produces logs,
    metrics, outputs and a model just like any participant) AND the aggregator. Its training app
    cannot reach its own aggregator over the relay - the relay routes a *coordinator's* sends as
    broadcasts, not as client->aggregator messages - so the local update is handed to the aggregator
    directly through this bridge instead, and the aggregated result is handed back.

    Used as the training app's ``communicator``: ``aggregate(...)`` submits the local update and blocks
    for the aggregated result, mirroring ``FLNetCommunicatorClient.aggregate``. The aggregator thread
    calls ``take_contribution``/``publish_result`` once per round. All waits are bounded so a missing
    counterpart can never deadlock the run.
    """

    def __init__(self, coordinator_client_id: str, aggregator_id: str, timeout: float = 600.0):
        self.coordinator_client_id = coordinator_client_id
        self.aggregator_id = aggregator_id
        self.timeout = timeout
        self._cond = threading.Condition()
        self._contributions: dict[str, FLNetDataPackageDTO] = {}
        self._results: dict[str, Any] = {}

    # --- training-app side (mimics FLNetCommunicatorClient.aggregate) -------------------------
    def aggregate(self, data: Any, aggregator_name: str, communication_id: Optional[str] = None,
                  data_type: Any = None, smpc: Any = None, dp: Any = None) -> FLNetDataPackageDTO:
        comm_id = communication_id or "default"
        contribution = FLNetDataPackageDTO(
            data=data,
            meta=FLNetMessageMetaDTO(
                communicationId=comm_id,
                fromClientId=self.coordinator_client_id,
                toAggregator=aggregator_name,
            ),
        )
        deadline = time.monotonic() + self.timeout
        logger.info("[BRIDGE] coordinator training submitted contribution and is waiting for result (comm_id=%s)", comm_id)
        with self._cond:
            self._contributions[comm_id] = contribution
            self._cond.notify_all()
            while comm_id not in self._results:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._cond.wait(remaining):
                    self._contributions.pop(comm_id, None)
                    logger.error("[BRIDGE] coordinator training TIMED OUT waiting for aggregated result (comm_id=%s)", comm_id)
                    raise TimeoutError(
                        f"Coordinator aggregate timed out waiting for aggregated result "
                        f"(communication_id={comm_id})"
                    )
            result = self._results.pop(comm_id)
        logger.info("[BRIDGE] coordinator training received aggregated result (comm_id=%s)", comm_id)
        return FLNetDataPackageDTO(
            data=result,
            meta=FLNetMessageMetaDTO(
                communicationId=comm_id,
                fromClientId=self.aggregator_id,
                fromAggregator=aggregator_name,
            ),
        )

    # --- aggregator side ---------------------------------------------------------------------
    def take_contribution(self, communication_id: str, timeout: Optional[float] = None
                          ) -> Optional[FLNetDataPackageDTO]:
        """Block until the training app has submitted its update for this round, or the timeout
        elapses. Returns None on timeout so the aggregator can proceed with the relay clients alone
        rather than hanging."""
        wait_for = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + wait_for
        with self._cond:
            while communication_id not in self._contributions:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._cond.wait(remaining):
                    logger.warning("[BRIDGE] aggregator did NOT get coordinator contribution in time (comm_id=%s)", communication_id)
                    return None
            logger.info("[BRIDGE] aggregator picked up coordinator contribution (comm_id=%s)", communication_id)
            return self._contributions.pop(communication_id)

    def publish_result(self, communication_id: str, result: Any) -> None:
        """Hand the aggregated result back to the waiting training app. Always called once per round
        so the app thread cannot block forever, even if its contribution was dropped on timeout."""
        with self._cond:
            self._results[communication_id] = result
            self._cond.notify_all()
        logger.info("[BRIDGE] aggregator published aggregated result to coordinator training (comm_id=%s)", communication_id)

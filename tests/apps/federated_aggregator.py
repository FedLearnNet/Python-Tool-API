from __future__ import annotations

from typing import Any, Optional

import numpy as np

from pyfedappwrap.engine.federated import AppAggregator, FLNetMessageMetaDTO


class MeanVectorAggregator(AppAggregator):
    def aggregate(self, data: list[Any], n_clients: int,
                  meta: Optional[FLNetMessageMetaDTO] = None) -> Any:
        stacked = np.stack(data)
        return np.mean(stacked, axis=0)

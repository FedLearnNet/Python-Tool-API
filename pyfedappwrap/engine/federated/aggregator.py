from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from pyfedappwrap.engine.federated.models import FLNetMessageMetaDTO


class AppAggregator(ABC):
    @abstractmethod
    def aggregate(self, data: list[Any], n_clients: int,
                  meta: Optional[FLNetMessageMetaDTO] = None) -> Any:
        """
        Aggregate client payloads into a single result.
        """
        raise NotImplementedError

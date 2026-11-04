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

    def save_model(self, aggregated: Any) -> Optional[str]:
        """
        Optionally persist the final round's aggregated result as a model file inside
        ``system_settings.model_dir`` and return its file name so the engine can upload it.

        ``aggregated`` is the value this aggregator's own ``aggregate()`` returned for the last
        completed round - aggregators are otherwise stateless, so the engine cannot reconstruct it
        on its own. Returning ``None`` (the default) means there is no model to upload.
        """
        return None

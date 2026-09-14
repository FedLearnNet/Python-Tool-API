from abc import ABC, abstractmethod
from typing import TypeVar, Generic

import pandas as pd

from pyfedappwrap.learning.base_app import BaseApp
from pyfedappwrap.learning.run_runfig import AppConfig, AppOutputConfig
from pyfedappwrap.types.export.export_config import ExportInputConfig
from pyfedappwrap.types.transformation.transformer_config import TransformerInputConfig

C = TypeVar('C', bound=AppConfig)
O = TypeVar('O', bound=AppOutputConfig)


class BaseExporterAPP(BaseApp[C, ExportInputConfig, O], ABC,
                      Generic[C, O]):

    def __init__(self):
        super().__init__()

    @abstractmethod
    def export(self, df: pd.DataFrame) -> O:
        pass

    def run_train(self, data: TransformerInputConfig) -> O:
        return self.export(data.input)

    def run_prediction(self, data: TransformerInputConfig) -> O:
        return self.export(data.input)

    def _save(self) -> str:
        pass

    def _load(self, path: str):
        pass

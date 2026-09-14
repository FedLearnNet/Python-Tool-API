import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypeVar, Generic

import pandas as pd

from pyfedappwrap.learning.base_app import BaseApp
from pyfedappwrap.learning.run_runfig import AppConfig, AppInputConfig, AppOutputConfig

C = TypeVar('C', bound=AppConfig)
I = TypeVar('I', bound=AppInputConfig)
O = TypeVar('O', bound=AppOutputConfig)


class BaseExtractorAdopterAPP(BaseApp[C, I, O], ABC,
                              Generic[C, I, O]):

    def __init__(self):
        super().__init__()

    def run_train(self, data: I) -> O:
        return self.run_prediction(data)

    def run_prediction(self, data: I) -> O:
        return self.run_adopter()

    def to_csv(self, result: Path | pd.DataFrame) -> Path:
        if isinstance(result, Path):
            return result
        unq_id = uuid.uuid4()
        return self.save_df(result, str(unq_id))

    @abstractmethod
    def run_adopter(self) -> O:
        pass

    def _save(self) -> str:
        pass

    def _load(self, path: str):
        pass

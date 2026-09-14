from abc import ABC, abstractmethod
from typing import Generic

from pyfedappwrap.learning.base_app import BaseApp, C, I, O


class BasePrePostProcessApp(BaseApp[C, I, O], ABC, Generic[C, I, O]):
    def __init__(self):
        super().__init__()

    def run_train(self, data: I) -> O:
        return self.run_process(data)

    def run_prediction(self, data: I) -> O:
        return self.run_process(data)

    @abstractmethod
    def run_process(self, data: I) -> O:
        pass

    def _save(self) -> str:
        pass

    def _load(self, path: str):
        pass


class BaseEvaluationApp(BaseApp[C, I, O], ABC, Generic[C, I, O]):
    def __init__(self):
        super().__init__()

    def run_train(self, data: I) -> O:
        return self.run_evaluate(data)

    def run_prediction(self, data: I) -> O:
        return self.run_evaluate(data)

    @abstractmethod
    def run_evaluate(self, data: I) -> O:
        pass

    def _save(self) -> str:
        pass

    def _load(self, path: str):
        pass


class BaseSelfLearnedApp(BaseApp[C, I, O], ABC, Generic[C, I, O]):
    def __init__(self):
        super().__init__()

    def run_train(self, data: I) -> O:
        return self.run_algorithm(data)

    def run_prediction(self, data: I) -> O:
        return self.run_algorithm(data)

    @abstractmethod
    def run_algorithm(self, data: I) -> O:
        pass

    def _save(self) -> str:
        pass

    def _load(self, path: str):
        pass

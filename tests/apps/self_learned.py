import os
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from pydantic.dataclasses import dataclass

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.runtime import FedDBEngine
from pyfedappwrap.engine.runtime_lifecycle import EngineResult
from pyfedappwrap.learning.app_types import BaseSelfLearnedApp
from pyfedappwrap.learning.run_runfig import AppConfig, AppInputConfig, AppOutputConfig


@dataclass
class MyAppConfig(AppConfig):
    multiplier: int = 4


@dataclass
class MyAppInputConfig(AppInputConfig):
    input: Any = None


@dataclass
class MyAppOutputConfig(AppOutputConfig):
    output: Any = None


class SelfLearnedTestApp(BaseSelfLearnedApp[MyAppConfig, MyAppInputConfig, MyAppOutputConfig]):
    def __init__(self):
        super().__init__()

    def run_algorithm(self, data: MyAppInputConfig) -> MyAppOutputConfig:
        self.logger.info("Training")
        self.logger.info(f"Received input: {data}")
        df: pd.DataFrame = data.input
        for i in range(10):
            self.send_metric("accuracy", i, i)
            self.send_metric("loss", i, i)
            self.send_metric("loss2", i, i)

        data = MyAppOutputConfig(output=df)
        return data


class SelfLearnedTestAppIris(SelfLearnedTestApp):
    def __init__(self):
        super().__init__()

    def get_test_data(self) -> Optional[dict[str, Path]]:
        return {"input": Path("data/iris.csv")}


if __name__ == '__main__':
    os.chdir("../../")
system_settings.data_dir = "data"
system_settings.config_settings_path = "tests/configs/data_analysis_app.yml"
system_settings.enable_remote_result_saving = False
print(system_settings)
engine = FedDBEngine(test_mode=True)
engine.register(SelfLearnedTestApp())

if __name__ == '__main__':
    engine.start()
    exit_payload: EngineResult | None = engine.wait_until_stop()
    assert exit_payload is None

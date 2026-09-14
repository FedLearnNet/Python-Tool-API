import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any
from typing_extensions import override

from examples.config import MyAppInputConfig
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.runtime import FedDBEngine
from pyfedappwrap.engine.runtime_lifecycle import EngineResult
from pyfedappwrap.learning.run_runfig import AppConfig, OneCSVOuputConfig
from pyfedappwrap.types.databaseadopter.base_importer import BaseExtractorAdopterAPP


@dataclass
class MyAppConfig(AppConfig):
    multiplier: int = 4


class DatabaseAdopterTest(
    BaseExtractorAdopterAPP[MyAppConfig, MyAppInputConfig, OneCSVOuputConfig]):

    def run_adopter(self) -> OneCSVOuputConfig:
        return OneCSVOuputConfig(output=Path("data/iris_adopter.csv"))

    def __init__(self):
        super().__init__()

    @override
    def get_test_hyperparams(self) -> Optional[dict[str, Any]]:
        return {"multiplier": 5}

if __name__ == '__main__':
    os.chdir("../../")
system_settings.data_dir = "data"
system_settings.config_settings_path = "tests/configs/data_base_adopter_app.yml"
system_settings.enable_remote_result_saving = False
print(system_settings)
engine = FedDBEngine(test_mode=True)
engine.register(DatabaseAdopterTest())

if __name__ == '__main__':
    engine.start()
    exit_payload: EngineResult | None = engine.wait_until_stop()
    assert exit_payload is None

from pathlib import Path
from typing import Any, Optional
from typing_extensions import override

from pydantic.dataclasses import dataclass
from pyfedappwrap.learning.base_app import BaseApp, I, O
from pyfedappwrap.learning.run_runfig import AppConfig, AppInputConfig, AppOutputConfig


@dataclass
class MyAppConfig(AppConfig):
    hyper_param_config_7: str = "ef"
    hyper_param_config_6: bool = True
    hyper_param_config_8: str = "adfgadfg"


@dataclass
class MyAppInputConfig(AppInputConfig):
    input: Any = None


@dataclass
class MyAppOutputConfig(AppOutputConfig):
    output: Any = None


class MyAPP(BaseApp[MyAppConfig, MyAppInputConfig, MyAppOutputConfig]):

    def __init__(self):
        super().__init__()

    def run_train(self, data: MyAppInputConfig) -> MyAppOutputConfig:
        self.logger.info("Training")
        self.logger.info(f"Received input: {data}")

        for i in range(10):
            self.send_metric("accuracy", i, i)
            self.send_metric("loss", i, i)
            self.send_metric("loss2", i, i)

        data = MyAppOutputConfig(output=data.input)
        self.logger.error("Training failed")
        self.logger.warning("Training completed")

        return data


    def run_prediction(self, data: MyAppInputConfig) -> MyAppOutputConfig:
        data = MyAppOutputConfig(output=data.input)
        self.logger.warning("Training completed")

        return data

    def _save(self) -> str:
        name: str =  'dummy_file.txt'
        with open(name, 'w') as file:
            file.write('This is a dummy file.\n')
            file.write('It contains some example text.\n')
        return name

    def _load(self, path: str):
        with open(path, 'r') as file:
            content = file.read()
        self.logger.info(f"Loaded content from {path}: {content}")
        return content

    @override
    def get_test_hyperparams(self) -> Optional[dict[str, Any]]:
        return {"result_mapping": "prefix"}

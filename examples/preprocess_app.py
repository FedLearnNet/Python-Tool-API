import pandas as pd

from config import MyAppConfig, MyAppInputConfig, MyAppOutputConfig
from pyfedappwrap.learning.app_types import BasePrePostProcessApp


class MyTest(BasePrePostProcessApp[MyAppConfig, MyAppInputConfig, MyAppOutputConfig]):

    def __init__(self):
        super().__init__()

    def run_process(self, data: MyAppInputConfig) -> MyAppOutputConfig:
        # TODO REPLACE with your preprocessing logic
        # This is just an example that drops NA and duplicates
        self.logger.info("Training")
        df: pd.DataFrame = data.features
        df = df.dropna()
        df = df.dropna(axis=1)
        if self.config.drop_duplicates:
            df = df.drop_duplicates()
        return MyAppOutputConfig(
            processed=df,
        )

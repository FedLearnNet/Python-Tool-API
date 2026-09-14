import pandas as pd

from config import MyAppConfig, MyAppInputConfig, MyAppOutputConfig
from pyfedappwrap.types.databaseadopter.base_importer import BaseExtractorAdopterAPP


class MyTest(BaseExtractorAdopterAPP[MyAppConfig, MyAppInputConfig, MyAppOutputConfig]):

    def run_adopter(self) -> MyAppOutputConfig:
        # TODO REPLACE with your database adoption logic
        df = pd.DataFrame({
            "col1": [1, 2, 3],
            "col2": ["a", "b", "c"]
        })
        return MyAppOutputConfig(output=self.to_csv(df))

    def __init__(self):
        super().__init__()

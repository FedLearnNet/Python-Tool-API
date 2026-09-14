from pathlib import Path

import pandas as pd

from config import MyAppConfig, MyAppInputConfig, MyAppOutputConfig
from pyfedappwrap.learning.app_types import BaseEvaluationApp


class MyTest(BaseEvaluationApp[MyAppConfig, MyAppInputConfig, MyAppOutputConfig]):

    def __init__(self):
        super().__init__()

    def run_evaluate(self, data: MyAppInputConfig) -> MyAppOutputConfig:
        # TODO REPLACE with your evaluation logic
        df: pd.DataFrame = data.features
        self.logger.info("Evaluation")

        self.send_metric("rows", 0, int(len(df)))
        self.send_metric("cols", 0, int(len(df.columns)))
        self.send_metric("missing_cells", 1, int(df.isna().sum().sum()))

        out = Path("evaluation.txt")
        out.write_text(
            f"rows={len(df)}\ncols={len(df.columns)}\nmissing_cells={int(df.isna().sum().sum())}\n",
            encoding="utf-8",
        )

        return MyAppOutputConfig(report=out)

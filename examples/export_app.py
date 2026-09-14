from pathlib import Path

import pandas as pd

from config import MyAppConfig, MyAppOutputConfig
from pyfedappwrap.types.export.base_exporter import BaseExporterAPP


class MyTest(BaseExporterAPP[MyAppConfig, MyAppOutputConfig]):

    def __init__(self):
        super().__init__()

    def export(self, df: pd.DataFrame) -> MyAppOutputConfig:
        self.logger.info("exporting")

        self.send_metric("rows", 0, int(len(df)))
        self.send_metric("cols", 0, int(len(df.columns)))
        self.send_metric("missing_cells", 1, int(df.isna().sum().sum()))

        out = Path("evaluation.txt")
        out.write_text(
            f"rows={len(df)}\ncols={len(df.columns)}\nmissing_cells={int(df.isna().sum().sum())}\n",
            encoding="utf-8",
        )

        return MyAppOutputConfig(report=out)

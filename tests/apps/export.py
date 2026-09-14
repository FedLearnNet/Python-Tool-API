from pathlib import Path
from typing import Optional

import pandas as pd
from pydantic.dataclasses import dataclass

from pyfedappwrap.learning.run_runfig import AppConfig, AppOutputConfig
from pyfedappwrap.types.export.base_exporter import BaseExporterAPP


@dataclass
class ExportTestConfig(AppConfig):
    report_name: str = "report"


@dataclass
class ExportTestOutputConfig(AppOutputConfig):
    report: Optional[Path] = None


class ExportTestApp(BaseExporterAPP[ExportTestConfig, ExportTestOutputConfig]):

    def export(self, df: pd.DataFrame) -> ExportTestOutputConfig:
        out = Path(f"{self.config.report_name}.txt")
        out.write_text(f"rows={len(df)}\ncols={len(df.columns)}\n", encoding="utf-8")
        return ExportTestOutputConfig(report=out)

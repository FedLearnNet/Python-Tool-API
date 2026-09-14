from typing import Any

from pydantic.dataclasses import dataclass

from pyfedappwrap.learning.run_runfig import AppInputConfig


@dataclass
class ExportInputConfig(AppInputConfig):
    input: Any = None

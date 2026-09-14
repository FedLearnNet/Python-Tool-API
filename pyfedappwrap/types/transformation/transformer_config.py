from pathlib import Path
from typing import Optional, Dict, Any

from pydantic.dataclasses import dataclass

from pyfedappwrap.learning.run_runfig import AppOutputConfig, AppConfig, AppInputConfig


@dataclass
class BaseTransformerConfig(AppConfig):
    input_mapping: Optional[Dict[str, str]] = None
    return_mapping: Optional[Dict[str, str]] = None
    column: Optional[str] = None

    def is_on_row(self):
        return self.input_mapping is not None and self.return_mapping is not None and self.column is None


@dataclass
class TransformerInputConfig(AppInputConfig):
    input: Any = None


@dataclass
class TransformerOutputConfig(AppOutputConfig):
    output: Optional[Path] = None

from pathlib import Path
from typing import Any

import pandas as pd

from pyfedappwrap.engine.config.config import FederatedAppBaseConfigDTO, ToolConfigDataType
from pyfedappwrap.engine.validate.dto import ToolFileEvaluationResultDTO
from pyfedappwrap.engine.validate.profiler import profile_table_from_path, profile_table_from_df
from pyfedappwrap.engine.validate.validate_file import validate_json, validate_text_or_string, \
    validate_html, validate_image
from pyfedappwrap.engine.validate.validate_table import validate_table_profile


class ValidatorService:
    def __init__(self, data: Any, cfg: FederatedAppBaseConfigDTO):
        self.cfg = cfg
        self.data = data
        self.is_pandas_df = False
        self.is_path = False
        if isinstance(data, Path) and data.exists():
            self.is_path = True
        elif isinstance(data, pd.DataFrame):
            self.is_pandas_df = True

    def validate(self) -> ToolFileEvaluationResultDTO:
        t = self.cfg.type
        if t in (ToolConfigDataType.CSV, ToolConfigDataType.TSV):
            profile = None
            if self.is_pandas_df:
                profile = profile_table_from_df(self.data, self.cfg, self.cfg.name,
                                                override_headers=False)
            elif self.is_path:
                profile = profile_table_from_path(self.data, self.cfg)
            else:
                raise ValueError(
                    "Data must be a pandas DataFrame or a valid file path for tabular data.")
            result = validate_table_profile(self.cfg, profile)
            result.name = self.cfg.name
            return result
        if t == ToolConfigDataType.JSON:
            return validate_json(self.data, self.cfg.name)
        if t == ToolConfigDataType.HTML:
            return validate_html(self.data, self.cfg.name)
        if t == ToolConfigDataType.IMAGE:
            return validate_image(self.data, self.cfg.name)

        return validate_text_or_string(self.data, self.cfg.name)

from pydantic.dataclasses import dataclass

from pyfedappwrap.learning.run_runfig import AppInputConfig


@dataclass
class DatabaseAdopterInputConfig(AppInputConfig):
    pass
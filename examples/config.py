from dataclasses import dataclass

from pyfedappwrap.learning.run_runfig import (AppConfig, AppInputConfig, AppOutputConfig)


@dataclass
class MyAppConfig(AppConfig):
    # TODO COPY your config from your config detail page
    pass

@dataclass
class MyAppInputConfig(AppInputConfig):
    # TODO COPY your config from your config detail page
    pass


@dataclass
class MyAppOutputConfig(AppOutputConfig):
    # TODO COPY your config from your config detail page
    pass

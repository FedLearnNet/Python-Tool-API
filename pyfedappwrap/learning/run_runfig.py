from typing import Optional, Any, List

from pydantic.dataclasses import dataclass


@dataclass
class AppConfig:
    pass


@dataclass
class AppInputConfig:
    pass


@dataclass
class AppOutputVisualisations:
    visualisation: Optional[Any] = None
    name: Optional[str] = None
    description: Optional[str] = None

@dataclass
class AppOutputConfig:
    visualisations: Optional[List[AppOutputVisualisations]] = None

@dataclass
class NoInputConfig(AppInputConfig):
    pass

@dataclass
class OneCSVConfig(AppInputConfig):
    input: Any = None

@dataclass
class OneCSVOuputConfig(AppOutputConfig):
    output: Any = None
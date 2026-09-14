from typing import Annotated

from pydantic import BaseModel, Field


class PerformanceDTO(BaseModel):
    cpu: Annotated[float, Field(description="The CPU usage")]
    memory: Annotated[float, Field(description="The memory usage")]
    process: Annotated[str, Field(description="The process name")]
    timestamp: Annotated[int, Field(description="The timestamp")]


class ConsoleStdOutDTO(BaseModel):
    msg: Annotated[str, Field(description="The console message")]

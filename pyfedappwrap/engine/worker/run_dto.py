from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, Field, ConfigDict


class RunStatusTypes(Enum):
    PENDING = "PENDING"
    INITIALIZED = "INITIALIZED"
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"

    def __str__(self):
        return self.value.upper()


class UpdateTestRunDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: Annotated[int, Field(description="The run id", alias="runId")]
    status: Annotated[RunStatusTypes, Field(description="The status of the run")]
    error: Annotated[str | None, Field(description="The error message", default=None)]


class RunMetaDTO(BaseModel):
    """Free-form run metadata sent to the backend and stored as JSON (jsonb).

    ``timings`` maps metric name -> milliseconds (keys: RUNTIME, OVERHEAD_STARTUP,
    OVERHEAD_TEARDOWN, OVERHEAD_TOTAL). Backwards-compatible: new keys can be added without
    changing this contract. The remaining fields are reserved for follow-up (kept for parity
    with the backend RunMetaDTO; not populated yet)."""
    model_config = ConfigDict(populate_by_name=True)

    timings: Annotated[Optional[dict[str, int]], Field(default=None)]

    # reserved (not populated yet) — see backend RunMetaDTO for intent
    engine_version: Annotated[Optional[str], Field(default=None, alias="engineVersion")]
    peak_memory_mb: Annotated[Optional[int], Field(default=None, alias="peakMemoryMb")]
    avg_cpu_percent: Annotated[Optional[float], Field(default=None, alias="avgCpuPercent")]



    cold_start: Annotated[Optional[bool], Field(default=None, alias="coldStart")]
    tool_image: Annotated[Optional[str], Field(default=None, alias="toolImage")]
    engine_version: Annotated[Optional[str], Field(default=None, alias="engineVersion")]
    random_seed: Annotated[Optional[int], Field(default=None, alias="randomSeed")]
    peak_memory_mb: Annotated[Optional[int], Field(default=None, alias="peakMemoryMb")]
    avg_cpu_percent: Annotated[Optional[float], Field(default=None, alias="avgCpuPercent")]
    input_row_count: Annotated[Optional[int], Field(default=None, alias="inputRowCount")]
    output_size_bytes: Annotated[Optional[int], Field(default=None, alias="outputSizeBytes")]



class FinishRunDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: Annotated[int, Field(description="The run id", alias="runId")]

    # Wrapper-measured run metadata (timings today). RUNTIME is always reported; overhead entries
    # are always sent — the learning-api decides whether to persist/show them.
    meta: Annotated[Optional[RunMetaDTO], Field(description="Run metadata", default=None)]

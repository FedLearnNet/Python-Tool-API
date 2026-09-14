from typing import Optional, List, Tuple, Annotated

from pydantic import BaseModel, ConfigDict, Field


class ColumnProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: Annotated[str, Field(description="Column name")]
    type: Annotated[str, Field(description="Column type")]
    count: Annotated[int, Field(description="Number of non-null values")]
    missing: Annotated[int, Field(description="Number of missing values")]
    unique_values: Annotated[
        Optional[int],
        Field(description="Amount of unique values", alias="uniqueValues")] = None
    mean: Annotated[Optional[float], Field(description="Mean value")] = None
    std: Annotated[Optional[float], Field(description="Standard deviation")] = None
    min: Annotated[Optional[float], Field(description="Minimum value")] = None
    p25: Annotated[Optional[float], Field(description="25th percentile")] = None
    median: Annotated[Optional[float], Field(description="Median value")] = None
    p75: Annotated[Optional[float], Field(description="75th percentile")] = None
    max: Annotated[Optional[float], Field(description="Maximum value")] = None
    top_categories: Annotated[
        Optional[List[Tuple[str, int]]],
        Field(description="Top categories if type eq categorical", alias="topCategories")] = None


class FileProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    file_name: Annotated[
        Optional[str], Field(description="The name of the file", alias="fileName")] = None
    rows_scanned: Annotated[
        int, Field(description="The number of rows scanned", alias="rowsScanned")]
    columns: Annotated[List[ColumnProfile], Field(description="The list of column profiles")]
    sample_rows: Annotated[
        List[str], Field(description="Sample rows from the file", alias="sampleRows")]


class LocalFiles(FileProfile):
    model_config = ConfigDict(populate_by_name=True)
    path: Annotated[str, Field(description="The local path to the file")]

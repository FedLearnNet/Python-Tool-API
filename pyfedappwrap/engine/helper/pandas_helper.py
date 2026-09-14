import tempfile
import uuid
from pathlib import Path as PathlibPath
from typing import Any

import pandas as pd


def get_save_path(prefix: str) -> Any:
    tmp_dir = PathlibPath(tempfile.mkdtemp(prefix="pandas_out_"))
    suffix = uuid.uuid4().hex[:4]
    return tmp_dir / f"{prefix}_{suffix}.csv"


def pandas_to_path_if_possible(obj: Any, prefix: str) -> Any:
    # DataFrame
    if isinstance(obj, pd.DataFrame):
        path = get_save_path(prefix)
        obj.to_csv(str(path), index=False)
        return path

    # Series
    if isinstance(obj, pd.Series):
        path = get_save_path(prefix)
        obj.to_frame().to_csv(str(path), index=False)
        return path
    return obj


def convert_dict_output_to_paths(data: dict[str, Any]) -> dict[str, Any]:
    """
    Walk a dict at first level only.
    Convert any pandas DataFrame / Series into CSV files and replace them with file paths.
    """
    result = {}
    for k, v in data.items():
        if v is None:
            continue
        converted = pandas_to_path_if_possible(v, k)
        result[k] = converted
    return result


def rename_columns_fast_inplace(
        df: pd.DataFrame,
        mapping: dict[str, str],
) -> pd.DataFrame:
    """
    Column renaming:
    - {old_col: new_col, ...}
    - Strict: all keys in mapping must exist in df.columns, else KeyError.
    - Fast path if mapping covers all columns: direct Index assignment.
    """
    if not mapping:
        return df

    cols = df.columns

    missing = [k for k in mapping.keys() if k not in cols]
    if missing:
        raise KeyError(f"Columns not found: {missing[:10]}{'...' if len(missing) > 10 else ''}")

    if len(mapping) >= len(cols) and all(c in mapping for c in cols):
        new_cols = [mapping[c] for c in cols]
        df.columns = new_cols
        return df

    new_cols = cols.rename(mapping)
    df.columns = new_cols
    return df

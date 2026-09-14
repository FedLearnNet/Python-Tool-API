import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

import pandas as pd

from pyfedappwrap.engine.config.config import FederatedAppInputConfigDTO, FederatedAppBaseConfigDTO, \
    ToolConfigDataType
from pyfedappwrap.engine.config.profile import ColumnProfile, FileProfile

_BOOL_TRUE = {"true", "1", "yes", "y", "t"}
_BOOL_FALSE = {"false", "0", "no", "n", "f"}


def _is_int_like(s: str) -> bool:
    try:
        # reject floats like "1.0"
        if re.fullmatch(r"[+-]?\d+", s.strip()):
            int(s)
            return True
        return False
    except Exception:
        return False


def _is_float_like(s: str) -> bool:
    try:
        float(s)
        return True
    except Exception:
        return False


def _is_bool_like(s: str) -> bool:
    v = s.strip().lower()
    return v in _BOOL_TRUE or v in _BOOL_FALSE


def _is_datetime_like(s: str) -> bool:
    # intentionally conservative (avoid false positives)
    # accept ISO-ish: 2024-01-31, 2024-01-31T12:34:56, with optional timezone Z
    v = s.strip()
    isoish = re.fullmatch(
        r"\d{4}-\d{2}-\d{2}"
        r"(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?",
        v
    )
    if not isoish:
        return False
    try:
        # datetime.fromisoformat doesn't accept 'Z' in old versions; normalize
        vv = v.replace("Z", "+00:00")
        datetime.fromisoformat(vv)
        return True
    except Exception:
        return False


def _infer_column_type(values: List[str]) -> str:
    """
    values: list of non-null strings
    """
    if not values:
        return "TEXT"

    # sample for speed if huge
    sample = values if len(values) <= 500 else values[:500]

    int_ok = 0
    float_ok = 0
    bool_ok = 0
    dt_ok = 0

    for v in sample:
        if _is_int_like(v):
            int_ok += 1
            float_ok += 1
            continue
        if _is_float_like(v):
            float_ok += 1
        if _is_bool_like(v):
            bool_ok += 1
        if _is_datetime_like(v):
            dt_ok += 1

    n = len(sample)
    # choose strongest match with high ratio to avoid weird misclassification
    if int_ok / n >= 0.98:
        return "INTEGER"
    if float_ok / n >= 0.98:
        return "NUMBER"
    if bool_ok / n >= 0.98:
        return "BOOLEAN"
    if dt_ok / n >= 0.98:
        return "DATETIME"
    return "TEXT"


def _infer_table_cfg_from_path(path: str) -> FederatedAppInputConfigDTO | None:
    """
    Infer whether `path` is a CSV/TSV and return a FederatedAppInputConfigDTO for it.
    Returns None if we can't infer a supported type.
    """
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".csv":
        return FederatedAppInputConfigDTO(
            name="guess profile",
            description="To guess profile",
            type=ToolConfigDataType.CSV,
            hasHeader=True,
        )

    if suffix == ".tsv":
        return FederatedAppInputConfigDTO(
            name="guess profile",
            description="To guess profile",
            type=ToolConfigDataType.TSV,
            hasHeader=True,
        )

    return None


def profile_from_path(
        path: str,
        *,
        max_rows_scan: int = 50_000,
        sample_rows: int = 10,
        top_k: int = 10,
) -> FileProfile:
    cfg = _infer_table_cfg_from_path(path)
    empty_profiler = FileProfile(file_name=path.split("/")[-1],
                                 rows_scanned=0,
                                 columns=[],
                                 sample_rows=[])
    if cfg is None:
        return empty_profiler
    try:
        return profile_table_from_path(
            path,
            cfg,
            max_rows_scan=max_rows_scan,
            sample_rows=sample_rows,
            top_k=top_k
        )
    except Exception as e:
        logging.getLogger(__name__).error(f"Error profiling file: {e}", exc_info=True)
        return empty_profiler


def profile_table_from_path(
        path: str | Path,
        cfg: FederatedAppBaseConfigDTO,
        *,
        max_rows_scan: int = 50_000,
        sample_rows: int = 10,
        top_k: int = 10,
) -> FileProfile:
    if cfg.type not in (ToolConfigDataType.CSV, ToolConfigDataType.TSV):
        raise ValueError(f"profile_table_from_path supports only CSV/TSV, got {cfg.type}")

    sep = "\t" if cfg.type == ToolConfigDataType.TSV else (cfg.delimiter or ",")
    has_header = bool(cfg.hasHeader)

    if isinstance(path, Path):
        path = str(path)

    df = pd.read_csv(
        path,
        sep=sep,
        header=0 if has_header else None,
        index_col=cfg.indexCol if cfg.indexCol else None,
        dtype=str,  # keep raw strings
        keep_default_na=False,  # empty -> ""
        nrows=max_rows_scan
    )
    file_name = path.split("/")[-1]
    return profile_table_from_df(
        df,
        cfg,
        file_name,
        sample_rows=sample_rows,
        top_k=top_k
    )


def profile_table_from_df(
        df: pd.DataFrame,
        cfg: FederatedAppBaseConfigDTO,
        file_name: str,
        *,
        sample_rows: int = 10,
        top_k: int = 10,
        override_headers: bool = True,
) -> FileProfile:
    if cfg.type not in (ToolConfigDataType.CSV,
                        ToolConfigDataType.TSV):
        raise ValueError(f"profile_table_from_path supports only CSV/TSV, got {cfg.type}")

    sep = "\t" if cfg.type == ToolConfigDataType.TSV else (cfg.delimiter or ",")
    has_header = bool(cfg.hasHeader)

    if override_headers:
        # If no header, create synthetic names col_1..col_n
        if not has_header:
            df.columns = [f"col_{i + 1}" for i in range(df.shape[1])]
        else:
            df.columns = [str(c).strip() for c in df.columns]

    # normalize: "" -> None and trim
    df = df.map(lambda x: None if x is None or str(x).strip() == "" else str(x).strip())

    rows_scanned = int(df.shape[0])

    # sample rows as csv-ish strings
    sample = []
    if rows_scanned > 0:
        take = df.head(sample_rows)
        for _, row in take.iterrows():
            # join with sep for readability; escape sep not needed for preview
            vals = ["" if v is None else str(v) for v in row.tolist()]
            sample.append(sep.join(vals))

    col_profiles: List[ColumnProfile] = []
    for col in df.columns:
        s = df[col]
        missing = int(s.isna().sum())
        non_null = s.dropna().astype(str).tolist()

        inferred = _infer_column_type(non_null)
        unique_values: Optional[int] = None
        top_categories: Optional[List[Tuple[str, int]]] = None

        # For TEXT-ish columns, compute top categories (and unique count if reasonably small)
        if inferred in ("TEXT", "DATETIME", "BOOLEAN"):
            # limit unique counting for huge text if desired
            unique_values = int(pd.Series(non_null).nunique(dropna=True)) if len(
                non_null) <= 200_000 else None
            vc = pd.Series(non_null).value_counts().head(top_k)
            top_categories = [(str(k), int(v)) for k, v in vc.items()]

            col_profiles.append(ColumnProfile(
                name=str(col),
                type=inferred,
                count=rows_scanned,
                missing=missing,
                unique_values=unique_values,
                top_categories=top_categories
            ))
            continue

        # Numeric columns: compute stats
        num = pd.to_numeric(s, errors="coerce")
        nn = num.dropna()
        if nn.empty:
            # fallback if parsing failed
            col_profiles.append(ColumnProfile(
                name=str(col),
                type="TEXT",
                count=rows_scanned,
                missing=missing,
                unique_values=int(pd.Series(non_null).nunique(dropna=True)) if len(
                    non_null) <= 200_000 else None,
                top_categories=[(str(k), int(v)) for k, v in
                                pd.Series(non_null).value_counts().head(top_k).items()]
            ))
            continue

        desc = nn.describe(percentiles=[0.25, 0.5, 0.75])
        mean = float(desc.get("mean")) if "mean" in desc else None
        std = float(desc.get("std")) if "std" in desc and not math.isnan(desc.get("std")) else None
        mn = float(desc.get("min")) if "min" in desc else None
        mx = float(desc.get("max")) if "max" in desc else None
        p25 = float(desc.get("25%")) if "25%" in desc else None
        med = float(desc.get("50%")) if "50%" in desc else None
        p75 = float(desc.get("75%")) if "75%" in desc else None

        unique_values = int(pd.Series(non_null).nunique(dropna=True)) if len(
            non_null) <= 200_000 else None

        col_profiles.append(ColumnProfile(
            name=str(col),
            type=inferred,
            count=rows_scanned,
            missing=missing,
            unique_values=unique_values,
            mean=mean, std=std,
            min=mn, p25=p25, median=med, p75=p75, max=mx,
            top_categories=None
        ))

    return FileProfile(
        file_name=file_name,
        rows_scanned=rows_scanned,
        columns=col_profiles,
        sample_rows=sample
    )

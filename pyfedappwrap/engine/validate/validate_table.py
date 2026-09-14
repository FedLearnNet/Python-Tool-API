import math
import re
from typing import Any, Dict, List, Optional

from pyfedappwrap.engine.config.config import (
    ToolConfigDataType,
    TabularSchemaDTO, NullValuePolicyDTO, FederatedAppBaseConfigDTO,
    FederatedAppConfigHyperParamDataType,
)
from pyfedappwrap.engine.config.profile import FileProfile, ColumnProfile
from pyfedappwrap.engine.validate.dto import ToolFileEvaluationResultDTO


def validate_table_profile(cfg: FederatedAppBaseConfigDTO,
                           profile: FileProfile) -> ToolFileEvaluationResultDTO:
    errors: List[str] = []
    meta: Dict[str, Any] = {
        "rowsScanned": profile.rows_scanned,
        "columnCount": len(profile.columns),
        "fileName": profile.file_name,
    }

    if cfg.type not in (ToolConfigDataType.CSV, ToolConfigDataType.TSV):
        return ToolFileEvaluationResultDTO(ok=False, errors=[
            f"Validator supports only CSV/TSV, got {cfg.type}"], meta=meta)

    if profile.rows_scanned <= 0:
        return ToolFileEvaluationResultDTO(ok=False, errors=["Table is empty (rowsScanned=0)."],
                                           meta=meta)

    cols_by_name = {c.name: c for c in profile.columns}

    # optional: shape check "100x5" or "?x5" or "100x?"
    if cfg.shape:
        _validate_shape(cfg.shape, profile.rows_scanned, len(profile.columns), errors)

    # optional: config-level min/max across numeric columns (best effort)
    if cfg.minValue is not None or cfg.maxValue is not None:
        _validate_global_minmax_profile(profile, cfg.minValue, cfg.maxValue, errors)

    schema = cfg.tabularSchema
    if schema:
        _validate_bounds_schema(schema, profile, errors)
        _validate_required_columns_schema(schema, cols_by_name, errors)
        _validate_allow_nulls_schema(schema, profile, errors)
        _validate_allow_only_numbers_schema(schema, profile, errors)

        if getattr(schema, "nullPolicy", None) is not None:
            delimiter = getattr(cfg, "delimiter", None)
            _validate_null_policy(schema.nullPolicy, profile, delimiter, errors)

        _validate_column_rules_schema(schema, profile, cols_by_name, errors)

    return ToolFileEvaluationResultDTO(ok=(len(errors) == 0), errors=errors, meta=meta)


def _validate_bounds_schema(schema: TabularSchemaDTO, profile: FileProfile,
                            errors: List[str]) -> None:
    rows = profile.rows_scanned
    cols = len(profile.columns)

    if schema.minRows is not None and rows < schema.minRows:
        errors.append(f"Too few rows: {rows} < minRows {schema.minRows}")
    if schema.maxRows is not None and rows > schema.maxRows:
        errors.append(f"Too many rows: {rows} > maxRows {schema.maxRows}")
    if schema.minColumns is not None and cols < schema.minColumns:
        errors.append(f"Too few columns: {cols} < minColumns {schema.minColumns}")
    if schema.maxColumns is not None and cols > schema.maxColumns:
        errors.append(f"Too many columns: {cols} > maxColumns {schema.maxColumns}")


def _validate_required_columns_schema(
        schema: TabularSchemaDTO, cols_by_name: Dict[str, ColumnProfile], errors: List[str]
) -> None:
    if not schema.requiredColumns:
        return
    for c in schema.requiredColumns:
        if c not in cols_by_name:
            errors.append(f"Missing required column: '{c}'")


def _validate_allow_nulls_schema(schema: TabularSchemaDTO, profile: FileProfile,
                                 errors: List[str]) -> None:
    """
    schema.prohibitedNulls == True  => enforce no missing
    schema.prohibitedNulls == False/None => do not enforce
    """
    if not getattr(schema, "prohibitedNulls", False):
        return

    for c in profile.columns:
        if c.missing > 0:
            errors.append(f"prohibitedNulls=true but column '{c.name}' has missing={c.missing}")
            return


def _validate_allow_only_numbers_schema(schema: TabularSchemaDTO, profile: FileProfile,
                                        errors: List[str]) -> None:
    if not schema.allowOnlyNumbers:
        return
    for c in profile.columns:
        if c.type not in ("INTEGER", "NUMBER"):
            errors.append(f"allowOnlyNumbers=true but column '{c.name}' is type={c.type}")
            return


def _matches_rule_type(rule_type: FederatedAppConfigHyperParamDataType, profile_type: str) -> bool:
    pt = (profile_type or "").upper()
    if rule_type == FederatedAppConfigHyperParamDataType.INTEGER:
        return pt == "INTEGER"
    if rule_type == FederatedAppConfigHyperParamDataType.FLOAT:
        return pt in ("INTEGER", "NUMBER")
    if rule_type == FederatedAppConfigHyperParamDataType.BOOLEAN:
        return pt == "BOOLEAN"
    if rule_type == FederatedAppConfigHyperParamDataType.CATEGORICAL:
        return pt in ("TEXT", "DATETIME")
    if rule_type == FederatedAppConfigHyperParamDataType.STRING:
        return True
    return True


def _validate_column_rules_schema(
        schema: TabularSchemaDTO,
        profile: FileProfile,
        cols_by_name: Dict[str, ColumnProfile],
        errors: List[str],
) -> None:
    if not schema.columns:
        return

    for col_name, rule in schema.columns.items():
        cp = cols_by_name.get(col_name)
        if cp is None:
            errors.append(f"Rule provided for unknown column '{col_name}'")
            continue

        # nullable rule
        nullable = True if rule.nullable is None else bool(rule.nullable)
        if not nullable and cp.missing > 0:
            errors.append(f"Column '{col_name}' is not nullable but missing={cp.missing}")
            return

        # type rule
        if rule.type is not None and not _matches_rule_type(rule.type, cp.type):
            errors.append(
                f"Column '{col_name}' type mismatch: expected {rule.type} but profile is {cp.type}")
            return

        # numeric min/max rule
        if rule.min is not None or rule.max is not None:
            if cp.type not in ("INTEGER", "NUMBER"):
                errors.append(
                    f"Column '{col_name}' has min/max rule but is not numeric (profile type={cp.type})")
                return
            if rule.min is not None and cp.min is not None and cp.min < rule.min:
                errors.append(f"Column '{col_name}' min {cp.min} < rule.min {rule.min}")
                return
            if rule.max is not None and cp.max is not None and cp.max > rule.max:
                errors.append(f"Column '{col_name}' max {cp.max} > rule.max {rule.max}")
                return

        # enumValues (best effort via topCategories)
        if rule.enumValues:
            allowed = set(rule.enumValues)
            if cp.top_categories:
                for v, _cnt in cp.top_categories:
                    if v not in allowed:
                        errors.append(f"Column '{col_name}' has category '{v}' not in enumValues")
                        return

        # regex (best effort via sampleRows heuristics)
        if rule.regex:
            try:
                rx = re.compile(rule.regex)
            except Exception as e:
                errors.append(f"Invalid regex for column '{col_name}': {e}")
                return

            idx = _column_index(profile.columns, col_name)
            if idx >= 0 and profile.sample_rows:
                for raw in profile.sample_rows:
                    if raw is None:
                        continue
                    parts = _split_row_heuristic(raw)
                    if idx < len(parts):
                        val = parts[idx].strip()
                        if val != "" and not rx.fullmatch(val):
                            errors.append(
                                f"Column '{col_name}' regex mismatch on sample value: '{val}'")
                            return


def _column_index(cols: List[ColumnProfile], name: str) -> int:
    for i, c in enumerate(cols):
        if c.name == name:
            return i
    return -1


def _validate_shape(shape: str, rows: int, cols: int, errors: List[str]) -> None:
    s = shape.strip().lower()
    parts = s.split("x")
    if len(parts) != 2:
        errors.append(
            f"Invalid shape format '{shape}'. Expected 'rowsxcols' like '100x5' or '?x5'.")
        return

    r, c = parts[0].strip(), parts[1].strip()

    if r != "?":
        try:
            exp_r = int(r)
            if rows != exp_r:
                errors.append(f"Shape rows mismatch: {rows} != {exp_r}")
        except Exception:
            errors.append(f"Invalid shape rows value '{r}' in '{shape}'")

    if c != "?":
        try:
            exp_c = int(c)
            if cols != exp_c:
                errors.append(f"Shape cols mismatch: {cols} != {exp_c}")
        except Exception:
            errors.append(f"Invalid shape cols value '{c}' in '{shape}'")


def _validate_global_minmax_profile(profile: FileProfile, min_v: Optional[float],
                                    max_v: Optional[float], errors: List[str]) -> None:
    for c in profile.columns:
        if c.type not in ("INTEGER", "NUMBER"):
            continue
        if min_v is not None and c.min is not None and c.min < min_v:
            errors.append(f"Global minValue={min_v} violated by column '{c.name}' min={c.min}")
            return
        if max_v is not None and c.max is not None and c.max > max_v:
            errors.append(f"Global maxValue={max_v} violated by column '{c.name}' max={c.max}")
            return


def _split_row_heuristic(raw: str) -> List[str]:
    # sampleRows are "sep-joined strings"; keep existing heuristic
    return re.split(r"[,\t]", raw, maxsplit=-1)


def _strip_optional_quotes(s: str) -> str:
    s2 = s.strip()
    if len(s2) >= 2 and ((s2[0] == '"' and s2[-1] == '"') or (s2[0] == "'" and s2[-1] == "'")):
        return s2[1:-1]
    return s2


def _validate_null_policy(
        policy: NullValuePolicyDTO,
        profile: FileProfile,
        delimiter: Optional[str],
        errors: List[str],
) -> None:
    """
    Best-effort enforcement:
    - Empty cells: uses ColumnProfile.missing (count of missing)
    - Empty/whitespace/null literal/zero-as-null: checks sample_rows tokens
    - NaN: checks numeric min/max/mean/std for NaN if present
    """
    cols_by_idx = profile.columns
    rows = profile.sample_rows or []

    # 1) empty cell (truly missing fields)
    if policy.prohibitedEmptyCell:
        for c in cols_by_idx:
            if c.missing > 0:
                errors.append(
                    f"nullPolicy.prohibitedEmptyCell=true but column '{c.name}' has missing={c.missing}")
                return

    # Decide how to split sample rows: if delimiter is known use it; else fallback heuristic
    splitter = None
    if delimiter:
        # treat \t too
        splitter = re.compile(re.escape(delimiter))
    # else: use heuristic re split on comma/tab

    # Setup null literals
    default_literals = ["null", "none", "na", "n/a", "nan"]
    literals = policy.nullLiterals or default_literals
    literals_lc = {x.strip().lower() for x in literals if x is not None}

    def iter_sample_cells() -> List[tuple[str, str]]:
        """Yield (colName, rawCellToken) for each sample row that has that col index."""
        out: List[tuple[str, str]] = []
        for raw in rows:
            if raw is None:
                continue
            if splitter:
                parts = splitter.split(raw)
            else:
                parts = _split_row_heuristic(raw)
            for idx, col in enumerate(cols_by_idx):
                if idx < len(parts):
                    out.append((col.name, parts[idx]))
        return out

    sample_cells = iter_sample_cells()

    # 2) empty string after parsing (quoted empty) - best effort: "" or '' or after stripping quotes becomes empty
    if policy.prohibitedEmptyString:
        for col_name, token in sample_cells:
            t = token.strip()
            if t in ('""', "''"):
                errors.append(
                    f"nullPolicy.prohibitedEmptyString=true but column '{col_name}' contains quoted empty string")
                return
            if _strip_optional_quotes(t) == "":
                # this also catches empty-cell tokens; keep message specific
                errors.append(
                    f"nullPolicy.prohibitedEmptyString=true but column '{col_name}' contains empty string token")
                return

    # 3) whitespace-only strings
    if policy.prohibitedWhitespaceString:
        for col_name, token in sample_cells:
            t = _strip_optional_quotes(token)
            if t != "" and t.strip() == "":
                errors.append(
                    f"nullPolicy.prohibitedWhitespaceString=true but column '{col_name}' contains whitespace-only token")
                return

    # 4) null literal tokens (case-insensitive)
    if policy.prohibitedNullLiterals:
        for col_name, token in sample_cells:
            t = _strip_optional_quotes(token).strip().lower()
            if t in literals_lc:
                errors.append(
                    f"nullPolicy.prohibitedNullLiterals=true but column '{col_name}' contains null literal '{token.strip()}'")
                return

    # 5) numeric NaN (best effort from aggregate stats)
    if policy.prohibitedNaN:
        for c in cols_by_idx:
            if c.type not in ("INTEGER", "NUMBER"):
                continue
            for v_name in ("min", "max", "mean", "std"):
                v = getattr(c, v_name, None)
                if isinstance(v, float) and math.isnan(v):
                    errors.append(
                        f"nullPolicy.prohibitedNaN=true but numeric column '{c.name}' has {v_name}=NaN")
                    return

    # 6) zero-as-null sentinel (token-based best effort)
    if policy.prohibitedZeroAsNull:
        zero_tokens = {"0", "0.0", "0.00", "-0", "-0.0", "-0.00"}
        for col_name, token in sample_cells:
            t = _strip_optional_quotes(token).strip()
            if t in zero_tokens:
                errors.append(
                    f"nullPolicy.prohibitedZeroAsNull=true but column '{col_name}' contains zero sentinel '{t}' in sample")
                return

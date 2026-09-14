import random
import re
import string
from pathlib import Path
from typing import List, Optional

from pyfedappwrap.engine.config.config import TabularSchemaDTO, ColumnRuleDTO

_EXTRA_COL_TYPES = ("NUMBER", "TEXT", "INTEGER", "BOOLEAN")


def generate_random_csv_from_schema(
        schema: TabularSchemaDTO,
        out_path: Path,
        *,
        delimiter: str = ",",
        seed: Optional[int] = None,
        include_header: bool = True,
) -> Path:
    rnd = random.Random(seed)

    chosen_cols = _choose_columns(schema, rnd)
    row_count = _choose_row_count(schema, rnd)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    rules = schema.columns or {}

    # global “no empty cells” policy if prohibitedNulls OR nullPolicy.prohibitedEmptyCell
    policy = getattr(schema, "nullPolicy", None)
    prohibit_empty_cell = bool(getattr(schema, "prohibitedNulls", False)) or bool(
        getattr(policy, "prohibitedEmptyCell", False)
    )
    allowOnlyNumbers = bool(getattr(schema, "allowOnlyNumbers", False))
    # null literals to avoid if prohibitedNullLiterals
    prohibit_null_literals = bool(getattr(policy, "prohibitedNullLiterals", False))
    null_literals = set()
    if prohibit_null_literals:
        lits = getattr(policy, "nullLiterals", None) or ["null", "none", "na", "n/a", "nan"]
        null_literals = {str(x).strip().lower() for x in lits if x is not None}

    with out_path.open("w", encoding="utf-8", newline="") as f:
        import csv

        w = csv.writer(f, delimiter=delimiter)
        if include_header:
            w.writerow(chosen_cols)

        for _ in range(row_count):
            row = []
            for col in chosen_cols:
                rule = rules.get(col)
                row.append(
                    _gen_cell_value(
                        col,
                        rule,
                        rnd,
                        delimiter=delimiter,
                        prohibit_empty_cell=prohibit_empty_cell,
                        prohibit_null_literals=prohibit_null_literals,
                        allowOnlyNumbers=allowOnlyNumbers,
                        null_literals=null_literals,
                        policy=policy,
                    )
                )
            w.writerow(row)

    return out_path


def _choose_row_count(schema: TabularSchemaDTO, rnd: random.Random) -> int:
    if schema.minRows is not None or schema.maxRows is not None:
        lo = schema.minRows if schema.minRows is not None else 0
        hi = schema.maxRows if schema.maxRows is not None else lo
        if hi < lo:
            hi = lo
        return rnd.randint(lo, hi)
    return rnd.randint(10, 100)


def _choose_col_count(schema: TabularSchemaDTO, base_count: int, rnd: random.Random) -> int:
    if schema.minColumns is not None or schema.maxColumns is not None:
        lo = schema.minColumns if schema.minColumns is not None else base_count
        hi = schema.maxColumns if schema.maxColumns is not None else max(lo, base_count)
        if hi < lo:
            hi = lo
        return rnd.randint(lo, hi)
    return base_count + rnd.randint(1, 5)


def _choose_columns(schema: TabularSchemaDTO, rnd: random.Random) -> List[str]:
    required = list(schema.requiredColumns or [])
    rules = schema.columns or {}

    known_cols = list(dict.fromkeys(required + list(rules.keys())))
    base_count = len(known_cols)
    target_count = _choose_col_count(schema, base_count, rnd)

    cols = list(known_cols)
    while len(cols) < target_count:
        cols.append(_unique_extra_name(cols, rnd))

    if len(cols) > target_count:
        required_set = set(required)
        trimmed = [c for c in cols if c in required_set]
        for c in cols:
            if c in required_set:
                continue
            if len(trimmed) >= target_count:
                break
            trimmed.append(c)
        cols = trimmed

    return cols


def _unique_extra_name(existing: List[str], rnd: random.Random) -> str:
    existing_set = set(existing)
    for _ in range(2000):
        candidate = f"extra_{rnd.choice(string.ascii_lowercase)}{rnd.randint(1, 999)}"
        if candidate not in existing_set:
            return candidate
    return f"extra_{len(existing) + 1}"


def _gen_cell_value(
        col_name: str,
        rule: Optional[ColumnRuleDTO],
        rnd: random.Random,
        *,
        delimiter: str,
        prohibit_empty_cell: bool,
        prohibit_null_literals: bool,
        allowOnlyNumbers: bool,
        null_literals: set,
        policy,
) -> str:
    # determine nullable for this column (rule beats schema-level)
    col_nullable = True if rule is None or rule.nullable is None else bool(rule.nullable)

    # If schema-level prohibits empty cell, override any nullable behavior.
    allow_empty = (col_nullable and not prohibit_empty_cell)

    # if empty is allowed, keep it rare (and never generate empty if prohibited)
    if allow_empty and rnd.random() < 0.03:
        return ""

    if allowOnlyNumbers:
        # If rule has min/max, honor it; otherwise emit a generic numeric.
        if rule is not None and (rule.min is not None or rule.max is not None):
            lo = float(rule.min) if rule.min is not None else 0.0
            hi = float(rule.max) if rule.max is not None else (lo + 100.0)
            if hi < lo:
                hi = lo
            val = str(rnd.randint(int(lo), int(hi))) if (
                    float(lo).is_integer() and float(hi).is_integer()) else _fmt_float(
                rnd.uniform(lo, hi))
        else:
            # generic numeric (prefer int to satisfy INTEGER-only profilers too)
            val = str(rnd.randint(0, 1_000_000))
        return _sanitize_token(val, delimiter, prohibit_null_literals, null_literals, policy, rnd)

    # enumValues
    if rule is not None and rule.enumValues:
        v = str(rnd.choice(rule.enumValues))
        return _sanitize_token(v, delimiter, prohibit_null_literals, null_literals, policy, rnd)

    # numeric min/max
    if rule is not None and (rule.min is not None or rule.max is not None):
        lo = float(rule.min) if rule.min is not None else 0.0
        hi = float(rule.max) if rule.max is not None else (lo + 100.0)
        if hi < lo:
            hi = lo

        # avoid zero-as-null if prohibitedZeroAsNull
        prohibit_zero = bool(getattr(policy, "prohibitedZeroAsNull", False))
        for _ in range(20):
            if _looks_int(lo) and _looks_int(hi) and rnd.random() < 0.7:
                val = str(rnd.randint(int(lo), int(hi)))
            else:
                val = _fmt_float(rnd.uniform(lo, hi))
            if prohibit_zero and val in ("0", "0.0", "0.00", "-0", "-0.0", "-0.00"):
                continue
            return _sanitize_token(val, delimiter, prohibit_null_literals, null_literals, policy,
                                   rnd)

        # fallback if we're stuck
        val = "1" if (lo <= 1 <= hi) else str(int(lo))
        return _sanitize_token(val, delimiter, prohibit_null_literals, null_literals, policy, rnd)

    # regex
    if rule is not None and rule.regex:
        v = _gen_from_regex_best_effort(rule.regex, rnd)
        if v is None:
            # controlled brute force: generate safe tokens and match
            try:
                rx = re.compile(rule.regex)
            except Exception:
                rx = None
            if rx is not None:
                for _ in range(500):
                    candidate = _rand_safe_text(rnd, 1, 24, delimiter)
                    if rx.fullmatch(candidate):
                        v = candidate
                        break
        if v is None:
            v = _rand_safe_text(rnd, 6, 12, delimiter)
        return _sanitize_token(v, delimiter, prohibit_null_literals, null_literals, policy, rnd)

    # default extra column behavior: always non-empty if prohibited
    v = _gen_default_value(rnd, delimiter)
    if prohibit_empty_cell and v == "":
        v = "x"
    return _sanitize_token(v, delimiter, prohibit_null_literals, null_literals, policy, rnd)


def _sanitize_token(
        v: str,
        delimiter: str,
        prohibit_null_literals: bool,
        null_literals: set,
        policy,
        rnd: random.Random,
) -> str:
    # ensure no delimiter/newlines/tabs/commas that could break sampleRows heuristics
    s = str(v)
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    if delimiter:
        s = s.replace(delimiter, " ")
    # also avoid commas regardless (your validator splits on comma/tab heuristically)
    s = s.replace(",", " ")

    s_stripped_lc = s.strip().lower()

    # if prohibited empty string
    if bool(getattr(policy, "prohibitedEmptyString", False)) and s.strip() == "":
        s = "x"

    # if prohibited whitespace-only
    if bool(getattr(policy, "prohibitedWhitespaceString", False)) and s != "" and s.strip() == "":
        s = "x"

    # if prohibited null literal
    if prohibit_null_literals and s_stripped_lc in null_literals:
        s = "x"

    return s


def _looks_int(x: float) -> bool:
    try:
        return float(x).is_integer()
    except Exception:
        return False


def _fmt_float(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".")


def _rand_safe_text(rnd: random.Random, min_len: int, max_len: int, delimiter: str) -> str:
    n = rnd.randint(min_len, max_len)
    alphabet = string.ascii_letters + string.digits + "_-."
    s = "".join(rnd.choice(alphabet) for _ in range(n))
    # make sure delimiter/comma not present
    s = s.replace(",", "_")
    if delimiter:
        s = s.replace(delimiter, "_")
    return s


def _gen_default_value(rnd: random.Random, delimiter: str) -> str:
    t = rnd.choice(_EXTRA_COL_TYPES)
    if t == "BOOLEAN":
        return "true" if rnd.random() < 0.5 else "false"
    if t == "INTEGER":
        return str(rnd.randint(1, 1000))  # avoid empty and common null-ish tokens
    if t == "NUMBER":
        return _fmt_float(rnd.uniform(0.001, 1000.0))
    return _rand_safe_text(rnd, 3, 16, delimiter)


def _gen_from_regex_best_effort(pattern: str, rnd: random.Random) -> Optional[str]:
    p = pattern.strip()

    # exact digits: ^\d{n}$ / ^[0-9]{n}$
    m = re.fullmatch(r"^\^?(\\d|\[0-9\])\{(\d+)\}\$?$", p)
    if m:
        n = int(m.group(2))
        return "".join(str(rnd.randint(0, 9)) for _ in range(n))

    # digits plus: ^\d+$
    if re.fullmatch(r"^\^?(\\d|\[0-9\])\+\$?$", p):
        n = rnd.randint(1, 12)
        return "".join(str(rnd.randint(0, 9)) for _ in range(n))

    # common “no whitespace” email
    if p in (r"^\S+@\S+\.\S+$", r"^\w+@\w+\.\w+$"):
        user = _rand_safe_text(rnd, 3, 10, "")
        dom = _rand_safe_text(rnd, 3, 8, "")
        tld = rnd.choice(["com", "org", "net", "de"])
        return f"{user}@{dom}.{tld}"

    # ISO date
    if p in (r"^\d{4}-\d{2}-\d{2}$", r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"):
        year = rnd.randint(1990, 2030)
        month = rnd.randint(1, 12)
        day = rnd.randint(1, 28)
        return f"{year:04d}-{month:02d}-{day:02d}"

    return None

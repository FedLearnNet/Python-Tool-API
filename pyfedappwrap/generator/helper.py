import random
import re
import string
import uuid
from datetime import date, datetime
from typing import Optional

TEXT_ALPHABET = string.ascii_letters + string.digits + " _-.:/@"
SAFE_TEXT_ALPHABET = string.ascii_letters + string.digits + "_-."


def random_text(rnd: random.Random, min_len: int, max_len: int,
                alphabet: str = TEXT_ALPHABET) -> str:
    n = rnd.randint(min_len, max_len)
    return "".join(rnd.choice(alphabet) for _ in range(n))


def rand_safe_text(rnd: random.Random, min_len: int, max_len: int, delimiter: str) -> str:
    s = random_text(rnd, min_len, max_len, SAFE_TEXT_ALPHABET)
    # make sure delimiter/comma not present
    s = s.replace(",", "_")
    if delimiter:
        s = s.replace(delimiter, "_")
    return s


def random_int(rnd: random.Random, lo: int, hi: int) -> int:
    """Inclusive random int; returns ``lo`` if the range is empty or inverted."""
    if lo >= hi:
        return lo
    return rnd.randint(lo, hi)


def random_float(rnd: random.Random, lo: float, hi: float) -> float:
    """Random float in [lo, hi]; returns ``lo`` if the range is empty or inverted."""
    if lo >= hi:
        return lo
    return rnd.uniform(lo, hi)


def random_date(rnd: random.Random, start_year: int = 1970, end_year: int = 2023) -> date:
    # day capped at 28 so every month is valid
    return date(rnd.randint(start_year, end_year), rnd.randint(1, 12), rnd.randint(1, 28))


def random_datetime(rnd: random.Random, start_year: int = 1970, end_year: int = 2023) -> datetime:
    d = random_date(rnd, start_year, end_year)
    return datetime(d.year, d.month, d.day, rnd.randint(0, 23), rnd.randint(0, 59),
                    rnd.randint(0, 59))


def parse_int_or_default(v: Optional[str], default: int) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_float_or_default(v: Optional[str], default: float) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def looks_int(x: float) -> bool:
    try:
        return float(x).is_integer()
    except Exception:
        return False


def fmt_float(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".")


def short_uuid4() -> str:
    return uuid.uuid4().hex[:8]


def gen_from_regex_best_effort(pattern: str, rnd: random.Random) -> Optional[str]:
    """Produce a matching value for a handful of common patterns, else ``None``."""
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
        user = rand_safe_text(rnd, 3, 10, "")
        dom = rand_safe_text(rnd, 3, 8, "")
        tld = rnd.choice(["com", "org", "net", "de"])
        return f"{user}@{dom}.{tld}"

    # ISO date
    if p in (r"^\d{4}-\d{2}-\d{2}$", r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"):
        year = rnd.randint(1990, 2030)
        month = rnd.randint(1, 12)
        day = rnd.randint(1, 28)
        return f"{year:04d}-{month:02d}-{day:02d}"

    return None


def gen_matching_text(pattern: str, rnd: random.Random, delimiter: str = "", attempts: int = 500) -> \
Optional[str]:
    """Best-effort pattern generation with a bounded brute-force fallback."""
    v = gen_from_regex_best_effort(pattern, rnd)
    if v is not None:
        return v
    try:
        rx = re.compile(pattern)
    except re.error:
        return None
    for _ in range(attempts):
        candidate = rand_safe_text(rnd, 1, 24, delimiter)
        if rx.fullmatch(candidate):
            return candidate
    return None

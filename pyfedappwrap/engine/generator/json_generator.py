from __future__ import annotations

import json
import random
import string
from pathlib import Path
from typing import Any, Dict, List, Optional


def generate_random_json(
    out_path: Path,
    *,
    seed: Optional[int] = None,
    min_keys: int = 5,
    max_keys: int = 25,
    max_depth: int = 3,
    max_list_len: int = 8,
    pretty: bool = True,
) -> Path:
    """
    Generates a random JSON file for test pipelines.

    Produces a top-level object with random keys and values:
      - scalars (str/int/float/bool/null)
      - lists
      - nested objects (up to max_depth)
    """
    rnd = random.Random(seed)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def rand_key() -> str:
        # stable + JSON-friendly keys
        n = rnd.randint(3, 12)
        return "".join(rnd.choice(string.ascii_lowercase + string.digits + "_") for _ in range(n))

    def rand_str(min_len: int = 3, max_len: int = 40) -> str:
        alphabet = string.ascii_letters + string.digits + " _-.:/@"
        n = rnd.randint(min_len, max_len)
        return "".join(rnd.choice(alphabet) for _ in range(n)).strip()

    def rand_scalar() -> Any:
        t = rnd.choice(["str", "int", "float", "bool", "null"])
        if t == "str":
            return rand_str()
        if t == "int":
            return rnd.randint(-10_000, 10_000)
        if t == "float":
            # keep it JSON-safe (no NaN/Inf)
            return round(rnd.uniform(-10_000.0, 10_000.0), 6)
        if t == "bool":
            return bool(rnd.getrandbits(1))
        return None

    def rand_value(depth: int) -> Any:
        if depth >= max_depth:
            return rand_scalar()

        t = rnd.choice(["scalar", "list", "object"])
        if t == "scalar":
            return rand_scalar()
        if t == "list":
            n = rnd.randint(0, max_list_len)
            return [rand_value(depth + 1) for _ in range(n)]
        # object
        n = rnd.randint(0, max_keys // 2)
        obj: Dict[str, Any] = {}
        for _ in range(n):
            obj[rand_key()] = rand_value(depth + 1)
        return obj

    root: Dict[str, Any] = {}
    k = rnd.randint(min_keys, max_keys)
    for _ in range(k):
        root[rand_key()] = rand_value(0)

    with out_path.open("w", encoding="utf-8") as f:
        if pretty:
            json.dump(root, f, ensure_ascii=False, indent=2, sort_keys=True)
        else:
            json.dump(root, f, ensure_ascii=False, separators=(",", ":"), sort_keys=False)

    return out_path
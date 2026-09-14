from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Optional

from pyfedappwrap.learning.run_runfig import AppOutputConfig


def _json_safe(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    if is_dataclass(obj):
        return _json_safe(asdict(obj))

    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]

    if callable(obj):
        return getattr(obj, "__name__", str(obj))

    return str(obj)


def visualisations_to_string(output: AppOutputConfig) -> Optional[str]:
    if output.visualisations is None:
        return None
    payload = [_json_safe(v) for v in output.visualisations]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

import json
from pathlib import Path
from typing import Any, Optional

from pyfedappwrap.engine.validate.dto import ToolFileEvaluationResultDTO


def validate_json(data: Any, name: Optional[str]) -> ToolFileEvaluationResultDTO:
    try:
        _read_json_value(data)
        return ToolFileEvaluationResultDTO.success(name)
    except Exception as e:
        return ToolFileEvaluationResultDTO.fail(str(e), name)


def validate_html(data: Any, name: Optional[str]) -> ToolFileEvaluationResultDTO:
    try:
        html = _read_text_value(data)
    except Exception as e:
        return ToolFileEvaluationResultDTO.fail(str(e), name)

    if not html.strip():
        return ToolFileEvaluationResultDTO.fail("HTML is empty.", name)

    lower = html.lstrip().lower()
    if "<html" not in lower and "<!doctype html" not in lower:
        return ToolFileEvaluationResultDTO.warn(
            "HTML does not appear to contain <html> or <!doctype html>.", name)

    return ToolFileEvaluationResultDTO.success(name)


def validate_image(data: Any, name: Optional[str]) -> ToolFileEvaluationResultDTO:
    try:
        blob = _read_bytes_value(data)
    except Exception as e:
        return ToolFileEvaluationResultDTO.fail(str(e), name)

    if not blob:
        return ToolFileEvaluationResultDTO.fail("Image is empty.", name)

    # magic number checks
    if _is_png(blob) or _is_jpeg(blob) or _is_gif(blob) or _is_webp(
            blob) or _is_bmp(blob):
        return ToolFileEvaluationResultDTO.success("Valid image (magic header).")

    return ToolFileEvaluationResultDTO.warn("Unknown image format (magic header not recognized).")


def validate_text_or_string(data: Any, name: Optional[str]) -> ToolFileEvaluationResultDTO:
    try:
        _read_text_value(data)
        return ToolFileEvaluationResultDTO.success(name)
    except Exception as e:
        return ToolFileEvaluationResultDTO.fail(str(e), name)


def _read_text_value(v: Any) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, Path):
        if not v.exists():
            raise ValueError(f"File does not exist: {v}")
        return v.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Expected str or Path, got: {type(v).__name__}")


def _read_bytes_value(v: Any) -> bytes:
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    if isinstance(v, Path):
        if not v.exists():
            raise ValueError(f"File does not exist: {v}")
        return v.read_bytes()
    raise ValueError(f"Expected bytes or Path, got: {type(v).__name__}")


def _read_json_value(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str):
        return json.loads(v)
    if isinstance(v, Path):
        if not v.exists():
            raise ValueError(f"File does not exist: {v}")
        return json.loads(v.read_text(encoding="utf-8", errors="strict"))
    raise ValueError(f"Expected dict/list/str/Path, got: {type(v).__name__}")


def _is_png(b: bytes) -> bool:
    return b.startswith(b"\x89PNG\r\n\x1a\n")


def _is_jpeg(b: bytes) -> bool:
    return b.startswith(b"\xff\xd8") and b.endswith(b"\xff\xd9")


def _is_gif(b: bytes) -> bool:
    return b.startswith(b"GIF87a") or b.startswith(b"GIF89a")


def _is_webp(b: bytes) -> bool:
    return len(b) >= 12 and b[0:4] == b"RIFF" and b[8:12] == b"WEBP"


def _is_bmp(b: bytes) -> bool:
    return b.startswith(b"BM")

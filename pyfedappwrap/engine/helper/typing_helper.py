from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, get_args, get_origin
from typing import (
    get_type_hints,
    Union,
)

import pandas as pd


def _type_to_string(tp: Any) -> str:
    """
    Converts a Python type annotation into a readable string.
    Handles:
      - Any
      - Path
      - pd.DataFrame
      - dict / list / tuple / set
      - Optional / Union
      - nested generics
    """
    if tp is Any:
        return "Any"

    origin = get_origin(tp)
    args = get_args(tp)

    if tp is pd.DataFrame:
        return "pd.DataFrame"

    if tp is Path:
        return "Path"

    if tp is dict:
        return "dict"

    if tp is list:
        return "list"

    if tp is tuple:
        return "tuple"

    if tp is set:
        return "set"

    if origin is Union:
        non_none_args = [a for a in args if a is not type(None)]
        has_none = len(non_none_args) != len(args)

        if has_none and len(non_none_args) == 1:
            return f"Optional[{_type_to_string(non_none_args[0])}]"

        return " | ".join(_type_to_string(a) for a in args)

    if origin is list:
        inner = _type_to_string(args[0]) if args else "Any"
        return f"list[{inner}]"

    if origin is dict:
        key_t = _type_to_string(args[0]) if len(args) > 0 else "Any"
        val_t = _type_to_string(args[1]) if len(args) > 1 else "Any"
        return f"dict[{key_t}, {val_t}]"

    if origin is tuple:
        if not args:
            return "tuple"
        return f"tuple[{', '.join(_type_to_string(a) for a in args)}]"

    if origin is set:
        inner = _type_to_string(args[0]) if args else "Any"
        return f"set[{inner}]"

    # For normal classes like str, int, custom DTOs, etc.
    if hasattr(tp, "__name__"):
        return tp.__name__

    return str(tp)


def get_pydantic_dataclass_field_types(dto_cls: type) -> dict[str, str]:
    """
    Returns a mapping:
        field_name -> type_as_string

    Works for pydantic.dataclasses.dataclass and normal dataclasses.
    """
    if not is_dataclass(dto_cls):
        raise TypeError(f"{dto_cls} is not a dataclass type")

    type_hints = get_type_hints(dto_cls, include_extras=True)

    result: dict[str, str] = {}
    for f in fields(dto_cls):
        annotated_type = type_hints.get(f.name, f.type)
        result[f.name] = _type_to_string(annotated_type)

    return result


def unwrap_optional(tp: Any) -> Any:
    origin = get_origin(tp)
    args = get_args(tp)

    if origin is Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return tp


def get_dataclass_field_types(dto_cls: type) -> dict[str, Any]:
    if not is_dataclass(dto_cls):
        raise TypeError(f"{dto_cls} is not a dataclass")

    type_hints = get_type_hints(dto_cls, include_extras=True)
    return {
        f.name: unwrap_optional(type_hints.get(f.name, f.type))
        for f in fields(dto_cls)
    }


def classify_expected_type(tp: Any) -> str:
    tp = unwrap_optional(tp)
    origin = get_origin(tp)
    args = get_args(tp)

    if tp is Any:
        return "dataframe_preferred"

    if tp is Path:
        return "path"

    if tp is pd.DataFrame:
        return "dataframe"

    if tp is str:
        return "text"

    if tp is bytes:
        return "binary"

    if tp in (int, float, bool):
        return "scalar"

    if tp is dict or origin is dict:
        return "json_dict"

    if tp is list or origin is list:
        return "json_list"

    if origin is Union:
        normalized = [unwrap_optional(a) for a in args if a is not type(None)]
        if Path in normalized:
            return "path"
        if pd.DataFrame in normalized or Any in normalized:
            return "dataframe_preferred"
        if any(a is dict or get_origin(a) is dict for a in normalized):
            return "json_dict"
        if any(a is list or get_origin(a) is list for a in normalized):
            return "json_list"
        if str in normalized:
            return "text"

    return "unknown"

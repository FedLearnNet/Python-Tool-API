from dataclasses import asdict, fields, is_dataclass
from typing import Any, get_args, get_origin, get_type_hints, Union

import numpy as np
from pydantic import BaseModel


class FLNetSerializer:
    TYPE_KEY = "__flnet_type__"
    NDARRAY_TYPE = "ndarray"
    DATACLASS_TYPE = "dataclass"

    def serialize(self, value: Any) -> Any:
        if isinstance(value, np.ndarray):
            return {
                self.TYPE_KEY: self.NDARRAY_TYPE,
                "dtype": str(value.dtype),
                "shape": list(value.shape),
                "data": value.tolist(),
            }
        if isinstance(value, BaseModel):
            return {
                self.TYPE_KEY: self.DATACLASS_TYPE,
                "class_name": value.__class__.__name__,
                "module": value.__class__.__module__,
                "data": {key: self.serialize(val) for key, val in value.model_dump().items()},
            }
        if is_dataclass(value) and not isinstance(value, type):
            return {
                self.TYPE_KEY: self.DATACLASS_TYPE,
                "class_name": value.__class__.__name__,
                "module": value.__class__.__module__,
                "data": {key: self.serialize(val) for key, val in asdict(value).items()},
            }
        if isinstance(value, dict):
            return {key: self.serialize(val) for key, val in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.serialize(item) for item in value]
        return value

    def deserialize(self, payload: Any, expected_type: Any = None) -> Any:
        if expected_type is None or expected_type is Any:
            return self._deserialize_generic(payload)
        if payload is None:
            return None

        origin = get_origin(expected_type)
        args = get_args(expected_type)

        if origin is Union:
            non_none_args = [arg for arg in args if arg is not type(None)]
            if not non_none_args:
                return None
            for arg in non_none_args:
                try:
                    return self.deserialize(payload, arg)
                except (TypeError, ValueError):
                    continue
            return self._deserialize_generic(payload)

        if origin in (list, tuple):
            item_type = args[0] if args else Any
            items = [self.deserialize(item, item_type) for item in payload]
            return tuple(items) if origin is tuple else items

        if origin is dict:
            value_type = args[1] if len(args) > 1 else Any
            return {
                key: self.deserialize(value, value_type)
                for key, value in payload.items()
            }

        if expected_type is np.ndarray:
            raw = self._deserialize_generic(payload)
            return np.asarray(raw)

        if isinstance(expected_type, type) and issubclass(expected_type, BaseModel):
            raw = self._unwrap_dataclass_payload(payload)
            values = {key: self.deserialize(value) for key, value in raw.items()}
            return expected_type.model_validate(values)

        if is_dataclass(expected_type):
            raw = self._unwrap_dataclass_payload(payload)
            # Resolve string annotations (PEP 563 / `from __future__ import annotations`)
            # so nested typed fields are deserialized instead of silently falling through.
            try:
                resolved_hints = get_type_hints(expected_type)
            except Exception:
                resolved_hints = {}
            values = {}
            for f in fields(expected_type):
                field_type = resolved_hints.get(f.name, f.type)
                values[f.name] = self.deserialize(raw.get(f.name), field_type)
            return expected_type(**values)

        return self._deserialize_generic(payload)

    def _unwrap_dataclass_payload(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict) and payload.get(self.TYPE_KEY) == self.DATACLASS_TYPE:
            return payload.get("data", {})
        if isinstance(payload, dict):
            return payload
        raise TypeError(f"Expected a dataclass payload dictionary, received {type(payload)!r}")

    def _deserialize_generic(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            payload_type = payload.get(self.TYPE_KEY)
            if payload_type == self.NDARRAY_TYPE:
                return np.asarray(payload.get("data", []), dtype=payload.get("dtype"))
            if payload_type == self.DATACLASS_TYPE:
                return {
                    key: self._deserialize_generic(value)
                    for key, value in payload.get("data", {}).items()
                }
            return {key: self._deserialize_generic(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._deserialize_generic(item) for item in payload]
        return payload

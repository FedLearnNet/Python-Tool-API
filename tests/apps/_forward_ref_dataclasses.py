"""Helper dataclasses with PEP 563 postponed annotations.

Declared in a dedicated module so `from __future__ import annotations` is
active at class-definition time — this is what makes `fields(cls)[i].type`
return strings, which is the exact shape the serializer fix is guarding
against.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class OuterWithNestedNdarray:
    name: str = ""
    vector: np.ndarray = field(default_factory=lambda: np.zeros(0))

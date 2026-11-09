import logging

import pandas as pd
import pytest

from pyfedappwrap.transformation.base_transformer import BaseTransformerAPP
from pyfedappwrap.transformation.config.transformer_config import BaseTransformerConfig


class _PatientApp(BaseTransformerAPP[BaseTransformerConfig]):
    """Bypasses BaseApp.__init__ (needs a runtime config) and delegates transform to a callable."""

    def __init__(self, fn, **config):
        self.fn = fn
        self.config = BaseTransformerConfig(patient_id_column="pid", **config)
        self.logger = logging.getLogger("test")

    def transform(self, data):
        return self.fn(data)


def _df() -> pd.DataFrame:
    return pd.DataFrame({
        "pid": ["p1", "p2", "p1", "p2", "p3"],
        "t": [2, 1, 1, 2, 1],
        "value": [10, 20, 30, 40, 50],
    })


def test_one_result_per_row_keeps_rows_and_maps_returns() -> None:
    seen = []

    def total(rows):
        seen.append(rows)
        s = sum(r["v"] for r in rows)
        return [{"total": s} for _ in rows]

    app = _PatientApp(total, input_mapping={"v": "value", "unit": "[VALUE]mg"},
                      return_mapping={"total": "patient_total"})
    out = app.function_on_patient(_df())

    assert seen[0] == [{"v": 10, "unit": "mg"}, {"v": 30, "unit": "mg"}]
    assert out["pid"].tolist() == ["p1", "p1", "p2", "p2", "p3"]
    assert out["patient_total"].tolist() == [40, 40, 60, 60, 50]


def test_row_order_reorders_and_filters() -> None:
    def latest_only(rows):
        idx = max(range(len(rows)), key=lambda i: rows[i]["t"])
        return [{"t": rows[idx]["t"]}], [idx]

    app = _PatientApp(latest_only, input_mapping={"t": "t"}, return_mapping={"t": "latest_t"})
    out = app.function_on_patient(_df())

    assert out["value"].tolist() == [10, 40, 50]
    assert out["latest_t"].tolist() == [2, 2, 1]


def test_empty_result_drops_patient() -> None:
    app = _PatientApp(lambda rows: [] if len(rows) > 1 else [None], input_mapping={"v": "value"})
    out = app.function_on_patient(_df())

    assert out["pid"].tolist() == ["p3"]
    assert out["value"].tolist() == [50]


def test_missing_patient_id_and_invalid_results_fail() -> None:
    df = _df()
    df.loc[0, "pid"] = None
    with pytest.raises(RuntimeError, match="missing the external patient id"):
        _PatientApp(lambda rows: rows).function_on_patient(df)

    too_many = _PatientApp(lambda rows: [{}] * (len(rows) + 1))
    with pytest.raises(RuntimeError, match="more results than the patient has rows"):
        too_many.function_on_patient(_df())

    filter_without_order = _PatientApp(lambda rows: [{}])
    with pytest.raises(RuntimeError, match="invalid patient row order"):
        filter_without_order.function_on_patient(_df())


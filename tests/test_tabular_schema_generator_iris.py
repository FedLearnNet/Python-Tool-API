from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, List, Dict

import pytest

from pyfedappwrap.engine.config.config import TabularSchemaDTO, ColumnRuleDTO, \
    FederatedAppInputConfigDTO, ToolConfigDataType, NullValuePolicyDTO
from pyfedappwrap.engine.config.profile import FileProfile, ColumnProfile
from pyfedappwrap.engine.validate.profiler import profile_table_from_path
from pyfedappwrap.engine.validate.validate_table import validate_table_profile

ROOT_DIR = Path(os.path.abspath(os.curdir))
IRIS_PATH = os.path.join(ROOT_DIR, 'data/iris_test.csv')

NULL_POLICY_CSV_PATH = os.path.join(ROOT_DIR, "data/null_policy_test.csv")


def generate_profile_for_iris() -> FileProfile:
    profile = profile_table_from_path(IRIS_PATH,
                                      FederatedAppInputConfigDTO(
                                          name="test_iris",
                                          description="Iris dataset for testing",
                                          type=ToolConfigDataType.CSV,
                                          hasHeader=True))
    return profile


def _expected_iris_schema_static() -> TabularSchemaDTO:
    required = ["sepal.length", "sepal.width", "petal.length", "petal.width", "variety"]

    return TabularSchemaDTO(
        minRows=150,
        maxRows=150,
        minColumns=5,
        maxColumns=5,
        allowOnlyNumbers=False,
        prohibitedNulls=False,
        requiredColumns=required,
        columns={
            "sepal.length": ColumnRuleDTO(nullable=False, min=4.3, max=7.9),
            "sepal.width": ColumnRuleDTO(nullable=False, min=2.0, max=4.4),
            "petal.length": ColumnRuleDTO(nullable=False, min=1.0, max=6.9),
            "petal.width": ColumnRuleDTO(nullable=False, min=0.1, max=2.5),
            "variety": ColumnRuleDTO(
                nullable=False,
                enumValues=["Setosa", "Virginica", "Versicolor"],
            ),
        },
    )


def _col(profile: FileProfile, name: str) -> ColumnProfile:
    for c in profile.columns:
        if c.name == name:
            return c
    raise AssertionError(f"Column '{name}' not found. Got: {[c.name for c in profile.columns]}")


def _infer_tabular_schema_from_profile(profile: FileProfile) -> TabularSchemaDTO:
    required = [c.name for c in profile.columns]

    allow_nulls = any(c.missing > 0 for c in profile.columns)
    allow_only_numbers = all(c.type == "NUMBER" for c in profile.columns)

    cols: Dict[str, ColumnRuleDTO] = {}
    for c in profile.columns:
        enum_values: Optional[List[str]] = None
        if c.type != "NUMBER" and c.top_categories:
            enum_values = [name for (name, _) in c.top_categories]

        cols[c.name] = ColumnRuleDTO(
            type=None,
            nullable=(c.missing > 0),
            regex=None,
            enumValues=enum_values,
            min=c.min if c.type == "NUMBER" else None,
            max=c.max if c.type == "NUMBER" else None,
            description=None,
        )

    return TabularSchemaDTO(
        minRows=profile.rows_scanned,
        maxRows=profile.rows_scanned,
        minColumns=len(profile.columns),
        maxColumns=len(profile.columns),
        allowOnlyNumbers=allow_only_numbers,
        prohibitedNulls=allow_nulls,
        requiredColumns=required,
        columns=cols,
    )


def test_iris_file_profile_is_correct() -> None:
    profile = generate_profile_for_iris()

    assert profile.rows_scanned == 150
    assert len(profile.columns) == 5
    assert profile.sample_rows is not None and len(profile.sample_rows) > 0

    assert [c.name for c in profile.columns] == [
        "sepal.length",
        "sepal.width",
        "petal.length",
        "petal.width",
        "variety",
    ]

    for name in ["sepal.length", "sepal.width", "petal.length", "petal.width", "variety"]:
        c = _col(profile, name)
        assert c.count == 150
        assert c.missing == 0

    sl = _col(profile, "sepal.length")
    assert sl.type == "NUMBER"
    assert sl.mean == pytest.approx(5.8433333333, rel=1e-6)
    assert sl.std == pytest.approx(0.8280661279, rel=1e-6)
    assert sl.min == pytest.approx(4.3, abs=1e-9)
    assert sl.max == pytest.approx(7.9, abs=1e-9)

    sw = _col(profile, "sepal.width")
    assert sw.type == "NUMBER"
    assert sw.mean == pytest.approx(3.0573333333, rel=1e-6)
    assert sw.std == pytest.approx(0.4358662840, rel=1e-6)
    assert sw.min == pytest.approx(2.0, abs=1e-9)
    assert sw.max == pytest.approx(4.4, abs=1e-9)

    pl = _col(profile, "petal.length")
    assert pl.type == "NUMBER"
    assert pl.mean == pytest.approx(3.758, rel=1e-6)
    assert pl.std == pytest.approx(1.7652982333, rel=1e-6)
    assert pl.min == pytest.approx(1.0, abs=1e-9)
    assert pl.max == pytest.approx(6.9, abs=1e-9)

    pw = _col(profile, "petal.width")
    assert pw.type == "NUMBER"
    assert pw.mean == pytest.approx(1.1993333333, rel=1e-6)
    assert pw.std == pytest.approx(0.7622376689, rel=1e-6)
    assert pw.min == pytest.approx(0.1, abs=1e-9)
    assert pw.max == pytest.approx(2.5, abs=1e-9)

    sp = _col(profile, "variety")
    assert sp.type != "NUMBER"
    assert sp.unique_values in (3, None)
    if sp.top_categories is not None:
        assert set(sp.top_categories) == {("Setosa", 50), ("Versicolor", 50), ("Virginica", 50)}


def test_static_tabular_schema_is_correct_for_iris() -> None:
    profile = generate_profile_for_iris()

    got = _infer_tabular_schema_from_profile(profile)
    exp = _expected_iris_schema_static()

    assert got.minRows == exp.minRows
    assert got.maxRows == exp.maxRows
    assert got.minColumns == exp.minColumns
    assert got.maxColumns == exp.maxColumns
    assert got.allowOnlyNumbers == exp.allowOnlyNumbers
    assert got.prohibitedNulls == exp.prohibitedNulls
    assert got.requiredColumns == exp.requiredColumns

    assert got.columns is not None
    assert exp.columns is not None
    assert set(got.columns.keys()) == set(exp.columns.keys())

    for name, exp_rule in exp.columns.items():
        got_rule = got.columns[name]

        assert got_rule.nullable == exp_rule.nullable

        if exp_rule.min is not None:
            assert got_rule.min == pytest.approx(exp_rule.min, abs=1e-9)
        if exp_rule.max is not None:
            assert got_rule.max == pytest.approx(exp_rule.max, abs=1e-9)

        if exp_rule.enumValues is not None:
            assert got_rule.enumValues is not None
            assert set(got_rule.enumValues) == set(exp_rule.enumValues)


def test_null_policy_is_enforced_for_null_policy_csv() -> None:
    profile = profile_table_from_path(
        NULL_POLICY_CSV_PATH,
        FederatedAppInputConfigDTO(
            name="test_null_policy",
            description="CSV to test nullPolicy enforcement",
            type=ToolConfigDataType.CSV,
            hasHeader=True,
            delimiter=",",
            tabularSchema=TabularSchemaDTO(
                prohibitedNulls=False,  # rely on nullPolicy, not coarse missing-rule
                nullPolicy=NullValuePolicyDTO(
                    prohibitedEmptyCell=True,
                    prohibitedEmptyString=True,
                    prohibitedWhitespaceString=True,
                    prohibitedNullLiterals=True,
                    prohibitedZeroAsNull=True,
                    nullLiterals=["null", "none", "na", "n/a"],  # case-insensitive
                ),
            ),
        ),
    )

    cfg = FederatedAppInputConfigDTO(
        name="validate_null_policy",
        description="Validate nullPolicy",
        type=ToolConfigDataType.CSV,
        hasHeader=True,
        delimiter=",",
        tabularSchema=TabularSchemaDTO(
            prohibitedNulls=False,
            nullPolicy=NullValuePolicyDTO(
                prohibitedEmptyCell=True,
                prohibitedEmptyString=True,
                prohibitedWhitespaceString=True,
                prohibitedNullLiterals=True,
                prohibitedZeroAsNull=True,
                nullLiterals=["null", "none", "na", "n/a"],
            ),
        ),
    )

    res = validate_table_profile(cfg, profile)
    assert res.ok is False
    assert res.errors
    assert any("nullPolicy." in e for e in res.errors)

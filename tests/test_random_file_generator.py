import json
import logging
import os
from pathlib import Path

from pyfedappwrap.engine.config.config import NullValuePolicyDTO, \
    ColumnRuleDTO, TabularSchemaDTO, FederatedAppInputConfigDTO, ToolConfigDataType
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.generator.generator import generate_random_text
from pyfedappwrap.engine.generator.html_generator import generate_random_html
from pyfedappwrap.engine.generator.image_generator import generate_random_image
from pyfedappwrap.engine.generator.json_generator import generate_random_json
from pyfedappwrap.engine.generator.table_generator import generate_random_csv_from_schema
from pyfedappwrap.engine.validate.profiler import profile_table_from_path
from pyfedappwrap.engine.validate.validate_table import validate_table_profile

ROOT_DIR = Path(os.path.abspath(os.curdir))
BASE_PATH = ROOT_DIR / system_settings.data_dir


def test_random_tabular_file_generator_all_prohibited() -> None:
    schema = TabularSchemaDTO(
        minRows=25,
        maxRows=40,
        minColumns=5,
        maxColumns=8,
        requiredColumns=["id", "age", "email", "group", "score"],
        prohibitedNulls=True,
        nullPolicy=NullValuePolicyDTO(
            prohibitedEmptyCell=True,
            prohibitedEmptyString=True,
            prohibitedWhitespaceString=True,
            prohibitedNullLiterals=True,
            prohibitedZeroAsNull=False,
            nullLiterals=["null", "none", "na", "n/a"],
        ),
        columns={
            "id": ColumnRuleDTO(nullable=False, regex=r"^\d{6}$"),
            "age": ColumnRuleDTO(nullable=False, min=18, max=99),
            "email": ColumnRuleDTO(nullable=False, regex=r"^\S+@\S+\.\S+$"),
            "group": ColumnRuleDTO(nullable=False, enumValues=["A", "B", "C"]),
            "score": ColumnRuleDTO(nullable=False, min=0, max=100),
        },
    )
    _generate_and_validate_random_tabular_file_generator_produces_valid_file(schema, "prohibited")


def test_random_tabular_file_generator_some_prohibited() -> None:
    schema = TabularSchemaDTO(
        minRows=15,
        maxRows=40,
        minColumns=5,
        maxColumns=15,
        requiredColumns=["id", "age", "email", "group", "score"],
        prohibitedNulls=True,
        nullPolicy=NullValuePolicyDTO(
            prohibitedEmptyCell=True,
            prohibitedEmptyString=True,
            prohibitedWhitespaceString=False,
            prohibitedNullLiterals=False,
            prohibitedZeroAsNull=False,
        ),
        columns={
            "id": ColumnRuleDTO(nullable=False, regex=r"^\d{6}$"),
            "age": ColumnRuleDTO(nullable=False, min=18, max=99),
            "email": ColumnRuleDTO(nullable=False, regex=r"^\S+@\S+\.\S+$"),
            "group": ColumnRuleDTO(nullable=False, enumValues=["A", "B", "C"]),
            "score": ColumnRuleDTO(nullable=False, min=0, max=100),
        },
    )
    _generate_and_validate_random_tabular_file_generator_produces_valid_file(schema,
                                                                             "sone_prohibited")


def test_random_tabular_file_generator_none_prohibited() -> None:
    schema = TabularSchemaDTO(
        minRows=15,
        maxRows=40,
        minColumns=5,
        maxColumns=15,
        requiredColumns=["id", "age", "email", "group", "score"],
        prohibitedNulls=False,
        columns={
            "id": ColumnRuleDTO(nullable=False, regex=r"^\d{6}$"),
            "age": ColumnRuleDTO(nullable=False, min=18, max=99),
            "email": ColumnRuleDTO(nullable=False, regex=r"^\S+@\S+\.\S+$"),
            "group": ColumnRuleDTO(nullable=False, enumValues=["A", "B", "C"]),
            "score": ColumnRuleDTO(nullable=False, min=0, max=100),
        },
    )
    _generate_and_validate_random_tabular_file_generator_produces_valid_file(schema, "nullable")


def test_random_tabular_file_generator_integers() -> None:
    schema = TabularSchemaDTO(
        minRows=25,
        maxRows=40,
        minColumns=5,
        maxColumns=8,
        allowOnlyNumbers=True
    )
    _generate_and_validate_random_tabular_file_generator_produces_valid_file(schema, "integers")


def test_generate_random_test_text_file() -> None:
    out = BASE_PATH / "gen_test_random_text.txt"
    try:
        generate_random_text(out, seed=1)
        assert out.exists()
        assert out.stat().st_size > 0
        content = out.read_text(encoding="utf-8")
        assert "\n" in content
        assert len(content.strip()) > 0
    finally:
        _cleanup(out)


def test_generate_random_html_file() -> None:
    out = BASE_PATH / "gen_test_random.html"
    try:
        generate_random_html(out, seed=2)
        assert out.exists()
        html = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "<body" in html
        assert "</html>" in html
    finally:
        _cleanup(out)


def test_generate_random_image_file_png() -> None:
    out = BASE_PATH / "gen_test_random.png"
    try:
        produced = generate_random_image(out, seed=3, width=128, height=96)

        assert produced.exists()
        assert produced.stat().st_size > 0
        raw = produced.read_bytes()
        assert raw.startswith(b"P6\n")
        _cleanup(produced)
    finally:
        _cleanup(out)


def test_generate_random_json_file() -> None:
    out = BASE_PATH / "gen_test_random.json"
    try:
        generate_random_json(out, seed=4)
        assert out.exists()
        assert out.stat().st_size > 0

        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert len(data) > 0
    finally:
        _cleanup(out)


def _cleanup(p: Path) -> None:
    logging.info("Removing generated file: %s", p)
    if p.exists():
        p.unlink()


def _generate_and_validate_random_tabular_file_generator_produces_valid_file(
        schema: TabularSchemaDTO, prefix: str = "random") -> None:
    file_name = prefix + "_schema_test.csv"
    out = BASE_PATH / file_name
    logging.info("Generating file: %s", file_name)
    cfg = FederatedAppInputConfigDTO(
        name="random_schema_profile",
        description="Profile generated file",
        type=ToolConfigDataType.CSV,
        hasHeader=True,
        delimiter=",",
    )

    try:
        generate_random_csv_from_schema(schema, out, delimiter=",", seed=1337, include_header=True)

        prof = profile_table_from_path(
            str(out),
            cfg
        )

        res = validate_table_profile(cfg, prof)

        assert res.ok is True, f"Expected generator to satisfy schema, got errors: {res.errors}"
        assert schema.minRows <= prof.rows_scanned <= schema.maxRows
        assert schema.minColumns <= len(prof.columns) <= schema.maxColumns

        col_names = [c.name for c in prof.columns]
        for req in schema.requiredColumns or []:
            assert req in col_names
    finally:
        _cleanup(out)

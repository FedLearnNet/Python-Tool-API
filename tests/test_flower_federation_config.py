import os

import pytest

from pyfedappwrap.engine.service.flower import federation_config as fc


@pytest.fixture
def flwr_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FLWR_HOME", str(tmp_path / ".flwr"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return tmp_path / ".flwr"


def test_flwr_home_resolution_order(tmp_path, monkeypatch):
    monkeypatch.delenv("FLWR_HOME", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert fc.flwr_home() == tmp_path / "xdg" / ".flwr"

    monkeypatch.setenv("FLWR_HOME", str(tmp_path / "explicit"))
    assert fc.flwr_home() == tmp_path / "explicit"

    monkeypatch.delenv("FLWR_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert fc.flwr_home() == fc.Path.home() / ".flwr"


def test_creates_the_file_fresh_with_a_default_pointer(flwr_home):
    name = fc.ensure_local_federation(8000)

    assert name == "flnet-local"
    content = fc.config_toml_path().read_text(encoding="utf-8")
    assert '[superlink]\ndefault = "flnet-local"' in content
    assert '[superlink.flnet-local]\naddress = "127.0.0.1:8000"\ninsecure = true' in content


def test_is_idempotent_for_the_same_port(flwr_home):
    fc.ensure_local_federation(8000)
    fc.ensure_local_federation(8000)

    content = fc.config_toml_path().read_text(encoding="utf-8")
    assert content.count("[superlink.flnet-local]") == 1
    assert content.count("127.0.0.1:8000") == 1


def test_updates_the_port_on_a_later_call_without_duplicating_the_section(flwr_home):
    fc.ensure_local_federation(8000)
    fc.ensure_local_federation(8001)

    content = fc.config_toml_path().read_text(encoding="utf-8")
    assert content.count("[superlink.flnet-local]") == 1
    assert "127.0.0.1:8001" in content
    assert "127.0.0.1:8000" not in content


def test_preserves_unrelated_existing_sections(flwr_home):
    fc.config_toml_path().parent.mkdir(parents=True, exist_ok=True)
    fc.config_toml_path().write_text(
        '[superlink]\ndefault = "local"\n\n'
        '[superlink.supergrid]\naddress = "api.flower.ai"\n\n'
        '[superlink.local]\naddress = ":local:"\n',
        encoding="utf-8",
    )

    fc.ensure_local_federation(8000)

    content = fc.config_toml_path().read_text(encoding="utf-8")
    assert '[superlink.supergrid]\naddress = "api.flower.ai"' in content
    assert '[superlink.local]\naddress = ":local:"' in content
    assert '[superlink.flnet-local]\naddress = "127.0.0.1:8000"\ninsecure = true' in content

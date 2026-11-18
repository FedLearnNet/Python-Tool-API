"""communicationEngine backward compatibility: old app.yml files (no such key) must still load,
defaulting to FL_NET; new, Flower-tagged app.yml files must load with communicationEngine=FLOWER."""
import shutil
from pathlib import Path

import pytest

from pyfedappwrap.engine.config.config import CommunicationEngine
from pyfedappwrap.engine.config.config_handler import load_config
from pyfedappwrap.engine.config.system_config import system_settings

FIXTURES = Path(__file__).parent / "configs"


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    readme = tmp_path / "README.md"
    readme.write_text("# Test app\n", encoding="utf-8")
    monkeypatch.setattr(system_settings, "read_me_path", str(readme))
    return tmp_path


def test_an_old_app_yml_without_communication_engine_defaults_to_fl_net(app_dir):
    app_yml = app_dir / "app.yml"
    shutil.copy(FIXTURES / "data_analysis_app.yml", app_yml)
    assert "communicationEngine" not in app_yml.read_text(encoding="utf-8")

    config = load_config(str(app_yml))

    assert config is not None
    assert config.communicationEngine == CommunicationEngine.FL_NET


def test_a_flower_tagged_app_yml_loads_with_the_flower_engine(app_dir):
    app_yml = app_dir / "app.yml"
    content = (FIXTURES / "data_analysis_app.yml").read_text(encoding="utf-8")
    content = content.replace("info:\n", "info:\n  communicationEngine: FLOWER\n", 1)
    app_yml.write_text(content, encoding="utf-8")

    config = load_config(str(app_yml))

    assert config is not None
    assert config.communicationEngine == CommunicationEngine.FLOWER

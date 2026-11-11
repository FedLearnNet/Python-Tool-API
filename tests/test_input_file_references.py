from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from pyfedappwrap.engine.config.config import FederatedAppInputConfigDTO, ToolConfigDataType
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.service.upload import helper
from pyfedappwrap.engine.worker import data_manager


@pytest.fixture
def input_config(monkeypatch, tmp_path):
    config = SimpleNamespace(appConfig=SimpleNamespace(input=[FederatedAppInputConfigDTO(
        name="data", type=ToolConfigDataType.CSV, required=True, description="Training data")]))
    monkeypatch.setattr(data_manager, "load_config", Mock(return_value=config))
    monkeypatch.setattr(data_manager, "get_data_dir", lambda: str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("as_path", [False, True])
@pytest.mark.parametrize("absolute", [False, True])
def test_reads_local_csv_from_string_or_path(input_config, as_path, absolute):
    file = input_config / "training.csv"
    file.write_text("x,y\n1,2\n3,4\n")
    reference = file if absolute else file.relative_to(input_config)

    result = data_manager.get_data({}, {"data": reference if as_path else str(reference)})

    pd.testing.assert_frame_equal(result["data"], pd.DataFrame({"x": [1, 3], "y": [2, 4]}))


@pytest.mark.parametrize("scheme", ["http://", r"http\://", "https://", r"https\://"])
def test_downloads_store_csv_without_joining_it_to_local_directory(input_config, monkeypatch, scheme):
    monkeypatch.setattr(system_settings, "http_url", "http://backend:8080/testembed/")
    monkeypatch.setattr(system_settings, "url_prefix_remove", "api")
    get = Mock(return_value=SimpleNamespace(status_code=200, content=b"x,y\n1,2\n3,4\n"))
    monkeypatch.setattr(helper.requests, "get", get)

    result = data_manager.get_data({}, {"data": scheme + "localhost:4201/api/files/1/download?secret=test%2Fsecret"})

    pd.testing.assert_frame_equal(result["data"], pd.DataFrame({"x": [1, 3], "y": [2, 4]}))
    get.assert_called_once_with("http://backend:8080/files/1/download?secret=test%2Fsecret", headers={})

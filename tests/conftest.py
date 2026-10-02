import shutil

import pytest

from pyfedappwrap.engine.config.system_config import system_settings
from tests import TEST_DATA_DIR

# Set before any test module imports the runtime: generator.BASE_PATH is derived from data_dir at import time
system_settings.data_dir = str(TEST_DATA_DIR)


@pytest.fixture(autouse=True, scope="session")
def output_dir(tmp_path_factory):
    """Results of test runs go to a temp dir (output_dir defaults to ./) that is removed after the session."""
    path = tmp_path_factory.mktemp("output")
    previous = system_settings.output_dir
    system_settings.output_dir = str(path)
    yield path
    system_settings.output_dir = previous
    shutil.rmtree(path, ignore_errors=True)

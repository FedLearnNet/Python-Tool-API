from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.runtime import FedDBEngine
from pyfedappwrap.engine.runtime_lifecycle import EngineResult
from tests.apps.analysis import AnalysisTestApp
from tests.apps.self_learned import SelfLearnedTestApp, SelfLearnedTestAppIris
from tests.apps.database_adopter import DatabaseAdopterTest
from tests.apps.preprocess import DataPreProcessTestApp
from tests.apps.export import ExportTestApp

system_settings.data_dir = "data"

def test_analysis():
    system_settings.config_settings_path = "tests/configs/data_analysis_app.yml"
    system_settings.enable_remote_result_saving = False
    engine = FedDBEngine(test_mode=True)
    engine.register(AnalysisTestApp())

    engine.start()
    exit_payload: EngineResult | None = engine.wait_until_stop()
    assert exit_payload is None

def test_self_learned():
    system_settings.config_settings_path = "tests/configs/data_analysis_app.yml"
    system_settings.enable_remote_result_saving = False
    engine = FedDBEngine(test_mode=True)
    engine.register(SelfLearnedTestApp())

    engine.start()
    exit_payload: EngineResult | None = engine.wait_until_stop()
    assert exit_payload is None

def test_self_learned_iris():
    system_settings.config_settings_path = "tests/configs/data_analysis_app.yml"
    system_settings.enable_remote_result_saving = False
    engine = FedDBEngine(test_mode=True)
    engine.register(SelfLearnedTestAppIris())

    engine.start()
    exit_payload: EngineResult | None = engine.wait_until_stop()
    assert exit_payload is None

def test_data_base_adopter():
    system_settings.config_settings_path = "tests/configs/data_base_adopter_app.yml"
    system_settings.enable_remote_result_saving = False
    engine = FedDBEngine(test_mode=True)
    engine.register(DatabaseAdopterTest())

    engine.start()
    exit_payload: EngineResult | None = engine.wait_until_stop()
    assert exit_payload is None

def test_data_pre_process():
    system_settings.config_settings_path = "tests/configs/data_analysis_app.yml"
    system_settings.enable_remote_result_saving = False
    print(system_settings)
    engine = FedDBEngine(test_mode=True)
    engine.register(DataPreProcessTestApp())

    engine.start()
    exit_payload: EngineResult | None = engine.wait_until_stop()
    assert exit_payload is None

def test_export():
    system_settings.config_settings_path = "tests/configs/data_export_app.yml"
    system_settings.enable_remote_result_saving = False
    engine = FedDBEngine(test_mode=True)
    engine.register(ExportTestApp())

    engine.start()
    exit_payload: EngineResult | None = engine.wait_until_stop()
    assert exit_payload is None

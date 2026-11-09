import inspect
import sys
from pathlib import Path

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.runtime import FedDBEngine
from pyfedappwrap.transformation.base_transformer import BaseTransformerAPP
from pyfedappwrap.transformation.factory.factory_builder import TEST_FILE
from pyfedappwrap.transformation.factory.factory_test import TransformationTester
from pyfedappwrap.transformation.factory.factory_test_result import TransformationTestCaseDTO


def run(transformer: type[BaseTransformerAPP], test_file: Path = Path(TEST_FILE)) -> None:
    """Serves the transformation in the engine, in test mode it is tested against ``test_file`` instead."""
    if system_settings.test_mode:
        case = TransformationTestCaseDTO.model_validate_json(test_file.read_text(encoding="utf-8"))
        source_code = inspect.getsource(sys.modules[transformer.__module__])
        result = TransformationTester(case.goal, case.source_goals, case.mode).test(source_code, case.data)
        print(result.message)
        sys.exit(0 if result.is_success else 1)
    engine = FedDBEngine()
    engine.register_transformer(transformer())
    engine.start()
    engine.wait_until_stop()

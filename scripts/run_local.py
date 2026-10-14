"""Runs scripts/local_app.py against a local platform. Start from the repository root: python -m scripts.run_local"""
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.runtime import FedDBEngine
from scripts.local_app import MyAPP
from tests import TEST_DATA_DIR

system_settings.config_settings_path = "scripts/app.yml"
system_settings.data_dir = str(TEST_DATA_DIR)
print(system_settings)

engine = FedDBEngine(test_mode=True)

engine.register(MyAPP())
# engine.register_transformer(MyTransformer())  # see scripts/local_transformer.py

if __name__ == '__main__':
    engine.start()
    engine.wait_until_stop()

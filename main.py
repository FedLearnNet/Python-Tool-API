from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.runtime import FedDBEngine
from test import MyAPP

print(system_settings)

engine = FedDBEngine(test_mode=True)

engine.register(MyAPP())
# engine.register_transformer(MyTransformer())

if __name__ == '__main__':
    engine.start()
    engine.wait_until_stop()

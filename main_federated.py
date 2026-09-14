from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.runtime import FedDBEngine
from tests.apps.federated_aggregator import MeanVectorAggregator
from tests.apps.federated_client import FederatedMeanClientApp

system_settings.config_settings_path = "app_federated.yml"
system_settings.fl_test.use_dockerized_controller = True
print(system_settings)

engine = FedDBEngine()

engine.register_aggregator(MeanVectorAggregator(), "mean")
engine.register_federated(FederatedMeanClientApp())

if __name__ == '__main__':
    engine.start()
    engine.wait_until_stop()

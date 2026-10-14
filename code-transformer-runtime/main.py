from pyfedappwrap.engine.runtime import FedDBEngine

from check import TransformationCheckObserver

if __name__ == "__main__":
    engine = FedDBEngine()
    engine.ws_client.register(TransformationCheckObserver(engine.ws_client))
    engine.start()
    engine.wait_until_stop()

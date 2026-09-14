from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic

from pyfedappwrap.engine.config.system_config import get_data_dir, get_output_dir
from pyfedappwrap.engine.service.controller.client import FLNetCommunicatorClient
from pyfedappwrap.learning.base_app import BaseApp, C, I, O


class BaseFederatedApp(BaseApp[C, I, O], ABC, Generic[C, I, O]):
    def __init__(self):
        super().__init__()
        self.federated_controller_url: str = ""
        self.federated_app_key: str = ""
        self.federated_controller_app_key: str = ""
        self.federated_client_id: str = ""
        self.federated_client_ids: list[str] = []
        self.federated_aggregator_id: str = ""
        self.federated_channel: str = ""
        self.communicator = None

    def set_app_key(self, app_key: str) -> None:
        self.federated_app_key = app_key

    def configure_federation(self,
                             *,
                             controller_url: str,
                             controller_app_key: str,
                             client_id: str,
                             client_ids: list[str],
                             aggregator_id: str,
                             channel: str,
                             app_key: str = ""):
        self.federated_controller_url = controller_url
        self.federated_controller_app_key = controller_app_key
        self.federated_client_id = client_id
        self.federated_client_ids = client_ids
        self.federated_aggregator_id = aggregator_id
        self.federated_channel = channel
        if app_key:
            self.federated_app_key = app_key

    def set_startup(self, websocket_client, upload_client, app_id, run_id, run_type,
                    lifecycle, stop_worker):
        super().set_startup(websocket_client, upload_client, app_id, run_id, run_type,
                            lifecycle, stop_worker)
        if self.communicator is None and self.federated_channel:
            self.communicator = self.build_federated_communicator()
        if self.communicator is not None and hasattr(self.communicator, "bind_notice_subject"):
            self.communicator.bind_notice_subject(websocket_client)

    def build_federated_communicator(self) -> FLNetCommunicatorClient:
        return FLNetCommunicatorClient(
            controller_url=self.federated_controller_url,
            app_key=self.federated_app_key,
            controller_app_key=self.federated_controller_app_key,
            client_id=self.federated_client_id,
            client_ids=self.federated_client_ids,
            aggregator_id=self.federated_aggregator_id,
            channel=self.federated_channel,
        )

    def resolve_local_data_path(self, filename: str) -> Path:
        return Path(get_data_dir()) / filename

    def resolve_local_output_path(self, filename: str) -> Path:
        configured_output = get_output_dir()
        base_dir = Path(configured_output or "output")
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir / filename

    def save_local_csv(self, dataframe, filename: str) -> Path:
        output_path = self.resolve_local_output_path(filename)
        dataframe.to_csv(output_path, index=False)
        return output_path

    @abstractmethod
    def run_train(self, data: I) -> O:
        pass

    @abstractmethod
    def run_prediction(self, data: I) -> O:
        pass

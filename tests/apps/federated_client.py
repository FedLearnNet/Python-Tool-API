from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic.dataclasses import dataclass

from pyfedappwrap.engine.config.system_config import get_data_dir
from pyfedappwrap.learning.federated import BaseFederatedApp
from pyfedappwrap.learning.run_runfig import AppConfig, AppInputConfig, AppOutputConfig


@dataclass
class FederatedClientConfig(AppConfig):
    communication_id: str = "round-1"
    output_filename: str = "result.csv"


@dataclass
class FederatedClientInput(AppInputConfig):
    input: Any = None


@dataclass
class FederatedClientOutput(AppOutputConfig):
    output: Any = None


class FederatedMeanClientApp(
    BaseFederatedApp[FederatedClientConfig, FederatedClientInput, FederatedClientOutput]
):
    def run_train(self, data: FederatedClientInput) -> FederatedClientOutput:
        # LOAD
        assert self.communicator is not None, "communicator must be set before run_train"
        config = self.config or FederatedClientConfig()
        if data is None or data.input is None:
            df = self._fallback_input_dataframe()
        else:
            df = data.input

        numeric_df = df.select_dtypes(include="number")
        if numeric_df.empty:
            raise ValueError("Federated mean demo requires at least one numeric input column.")

        # Reduce to vector
        local_vector = numeric_df.mean().to_numpy(dtype=float)
        communication_id = config.communication_id

        self.communicator.send_data_to_aggregator(
            local_vector,
            aggregator_name="mean",
            communication_id=communication_id,
        )
        response = self.communicator.await_data_from_aggregator(
            aggregator="mean",
            communication_id=communication_id,
            data_type=np.ndarray,
        )
        aggregated_df = pd.DataFrame([response.data], columns=numeric_df.columns)
        self.save_local_csv(aggregated_df, config.output_filename)
        return FederatedClientOutput(output=aggregated_df)

    def run_prediction(self, data: FederatedClientInput) -> FederatedClientOutput:
        return self.run_train(data)

    def _fallback_input_dataframe(self) -> pd.DataFrame:
        data_dir = Path(get_data_dir())
        csv_files = sorted(data_dir.rglob("*.csv")) if data_dir.exists() else []
        if csv_files:
            return pd.read_csv(csv_files[0])

        seed = sum(ord(char) for char in self.federated_client_id)
        rng = np.random.default_rng(seed)
        return pd.DataFrame(rng.random((4, 2)), columns=["x", "y"])

    def _save(self) -> str:
        return "client"

    def _load(self, path: str):
        return Path(path)

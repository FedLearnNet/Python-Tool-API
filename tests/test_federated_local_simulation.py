from pathlib import Path

import numpy as np
import pandas as pd

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.federated import (
    FLNetLocalParticipantConfigDTO,
    FLNetLocalTestConfigDTO,
)
from pyfedappwrap.engine.tests.federated.runner import LocalFederatedRunner
from pyfedappwrap.engine.federated.reporter import FederatedStatusReporter
from pyfedappwrap.engine.worker.run_dto import RunStatusTypes
from tests.apps.federated_aggregator import MeanVectorAggregator
from tests.apps.federated_client import FederatedMeanClientApp


def _prepare_participant_dir(base_dir: Path, rows: list[dict[str, float]] | None = None):
    data_dir = base_dir / "data"
    output_dir = base_dir / "output"
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    if rows is not None:
        pd.DataFrame(rows).to_csv(data_dir / "input.csv", index=False)


class FakeFederatedWsClient:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)

    def send_silent(self, message):
        self.messages.append(message)


def test_local_federated_runner_simulates_threaded_learning(tmp_path: Path):
    system_settings.config_settings_path = "app_federated.yml"
    aggregator_dir = tmp_path / "aggregator"
    client1_dir = tmp_path / "client1"
    client2_dir = tmp_path / "client2"

    _prepare_participant_dir(aggregator_dir)
    _prepare_participant_dir(client1_dir, [{"x": 1.0, "y": 3.0}, {"x": 3.0, "y": 5.0}])
    _prepare_participant_dir(client2_dir, [{"x": 5.0, "y": 7.0}, {"x": 7.0, "y": 9.0}])

    config = FLNetLocalTestConfigDTO(
        aggregator_id="aggregator",
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator",
                role="aggregator",
                base_dir=aggregator_dir,
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1",
                role="client",
                base_dir=client1_dir,
                input_file_paths={"input": "input.csv"},
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-2",
                role="client",
                base_dir=client2_dir,
                input_file_paths={"input": "input.csv"},
            ),
        ],
    )

    runner = LocalFederatedRunner(config, aggregators={"mean": MeanVectorAggregator()})
    results = runner.run({
        "client-1": FederatedMeanClientApp(),
        "client-2": FederatedMeanClientApp(),
    })

    assert all(result.success for result in results.values()), results
    expected = np.array([4.0, 6.0])
    assert np.allclose(results["aggregator"].result, expected)
    assert np.allclose(results["client-1"].result.output.iloc[0].to_numpy(dtype=float), expected)
    assert np.allclose(results["client-2"].result.output.iloc[0].to_numpy(dtype=float), expected)

    aggregator_output = pd.read_csv(aggregator_dir / "output" / "aggregated.csv")
    client1_output = pd.read_csv(client1_dir / "output" / "result.csv")
    client2_output = pd.read_csv(client2_dir / "output" / "result.csv")

    assert np.allclose(aggregator_output.iloc[0].to_numpy(dtype=float), expected)
    assert np.allclose(client1_output.iloc[0].to_numpy(dtype=float), expected)
    assert np.allclose(client2_output.iloc[0].to_numpy(dtype=float), expected)


def test_local_federated_runner_supports_filename_hyperparams(tmp_path: Path):
    system_settings.config_settings_path = "app_federated.yml"
    aggregator_dir = tmp_path / "aggregator"
    client1_dir = tmp_path / "client1"
    client2_dir = tmp_path / "client2"

    _prepare_participant_dir(aggregator_dir)
    _prepare_participant_dir(client1_dir, [{"x": 1.0, "y": 3.0}, {"x": 3.0, "y": 5.0}])
    _prepare_participant_dir(client2_dir, [{"x": 5.0, "y": 7.0}, {"x": 7.0, "y": 9.0}])

    (client1_dir / "data" / "demo_input.csv").write_text("x,y\n1,3\n3,5\n", encoding="utf-8")
    (client2_dir / "data" / "demo_input.csv").write_text("x,y\n5,7\n7,9\n", encoding="utf-8")

    config = FLNetLocalTestConfigDTO(
        aggregator_id="aggregator",
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator",
                role="aggregator",
                base_dir=aggregator_dir,
                hyper_params={
                    "communication_id": "demo-round",
                    "output_filename": "demo_aggregated.csv",
                },
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1",
                role="client",
                base_dir=client1_dir,
                hyper_params={
                    "communication_id": "demo-round",
                    "output_filename": "demo_result.csv",
                },
                input_file_paths={"input": "demo_input.csv"},
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-2",
                role="client",
                base_dir=client2_dir,
                hyper_params={
                    "communication_id": "demo-round",
                    "output_filename": "demo_result.csv",
                },
                input_file_paths={"input": "demo_input.csv"},
            ),
        ],
    )

    runner = LocalFederatedRunner(config, aggregators={"mean": MeanVectorAggregator()})
    results = runner.run({
        "client-1": FederatedMeanClientApp(),
        "client-2": FederatedMeanClientApp(),
    })

    assert all(result.success for result in results.values()), results
    expected = np.array([4.0, 6.0])
    aggregator_output = pd.read_csv(aggregator_dir / "output" / "demo_aggregated.csv")
    client1_output = pd.read_csv(client1_dir / "output" / "demo_result.csv")
    client2_output = pd.read_csv(client2_dir / "output" / "demo_result.csv")

    assert np.allclose(aggregator_output.iloc[0].to_numpy(dtype=float), expected)
    assert np.allclose(client1_output.iloc[0].to_numpy(dtype=float), expected)
    assert np.allclose(client2_output.iloc[0].to_numpy(dtype=float), expected)


def test_local_federated_runner_ignores_non_numeric_columns_in_client_input(tmp_path: Path):
    system_settings.config_settings_path = "app_federated.yml"
    aggregator_dir = tmp_path / "aggregator"
    client1_dir = tmp_path / "client1"
    client2_dir = tmp_path / "client2"

    _prepare_participant_dir(aggregator_dir)
    _prepare_participant_dir(client1_dir)
    _prepare_participant_dir(client2_dir)

    pd.DataFrame([
        {"x": 1.0, "y": 3.0, "label": "setosa"},
        {"x": 3.0, "y": 5.0, "label": "setosa"},
    ]).to_csv(client1_dir / "data" / "input.csv", index=False)
    pd.DataFrame([
        {"x": 5.0, "y": 7.0, "label": "virginica"},
        {"x": 7.0, "y": 9.0, "label": "virginica"},
    ]).to_csv(client2_dir / "data" / "input.csv", index=False)

    config = FLNetLocalTestConfigDTO(
        aggregator_id="aggregator",
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator",
                role="aggregator",
                base_dir=aggregator_dir,
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1",
                role="client",
                base_dir=client1_dir,
                input_file_paths={"input": "input.csv"},
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-2",
                role="client",
                base_dir=client2_dir,
                input_file_paths={"input": "input.csv"},
            ),
        ],
    )

    runner = LocalFederatedRunner(config, aggregators={"mean": MeanVectorAggregator()})
    results = runner.run({
        "client-1": FederatedMeanClientApp(),
        "client-2": FederatedMeanClientApp(),
    })

    assert all(result.success for result in results.values()), results
    expected = np.array([4.0, 6.0])
    assert np.allclose(results["aggregator"].result, expected)
    assert list(results["client-1"].result.output.columns) == ["x", "y"]
    assert list(results["client-2"].result.output.columns) == ["x", "y"]
    assert np.allclose(results["client-1"].result.output.iloc[0].to_numpy(dtype=float), expected)
    assert np.allclose(results["client-2"].result.output.iloc[0].to_numpy(dtype=float), expected)


def test_local_federated_runner_executes_client_app_workflow_and_reports_round_messages(tmp_path: Path):
    system_settings.config_settings_path = "app_federated.yml"
    system_settings.enable_remote_result_saving = False
    aggregator_dir = tmp_path / "aggregator"
    client1_dir = tmp_path / "client1"
    client2_dir = tmp_path / "client2"

    _prepare_participant_dir(aggregator_dir)
    _prepare_participant_dir(client1_dir, [{"x": 1.0, "y": 3.0}, {"x": 3.0, "y": 5.0}])
    _prepare_participant_dir(client2_dir, [{"x": 5.0, "y": 7.0}, {"x": 7.0, "y": 9.0}])

    config = FLNetLocalTestConfigDTO(
        aggregator_id="aggregator",
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator",
                role="aggregator",
                base_dir=aggregator_dir,
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1",
                role="client",
                base_dir=client1_dir,
                input_file_paths={"input": "input.csv"},
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-2",
                role="client",
                base_dir=client2_dir,
                input_file_paths={"input": "input.csv"},
            ),
        ],
    )
    ws_client = FakeFederatedWsClient()
    reporter = FederatedStatusReporter(ws_client, federated_run_id=55)
    client_1 = FederatedMeanClientApp()
    client_2 = FederatedMeanClientApp()
    runner = LocalFederatedRunner(
        config,
        aggregators={"mean": MeanVectorAggregator()},
        ws_client=ws_client,
        reporter=reporter,
        run_id=55,
    )

    results = runner.run({
        "client-1": client_1,
        "client-2": client_2,
    })

    assert all(result.success for result in results.values()), results
    assert client_1.finish_event.is_set()
    assert client_2.finish_event.is_set()
    assert client_1.get_status() == RunStatusTypes.FINISHED
    assert client_2.get_status() == RunStatusTypes.FINISHED
    assert reporter.get_counts("client-1")[0] >= 1
    assert reporter.get_counts("client-1")[1] >= 1
    log_worker_ids = {
        message.message.worker_id
        for message in ws_client.messages
        if getattr(message.type, "value", None) == "LOG_MESSAGE"
    }
    assert {"client-1", "client-2"}.issubset(log_worker_ids)
    assert any(getattr(message.type, "value", None) == "FEDERATED_ROUND_MESSAGE"
               for message in ws_client.messages)


def test_local_federated_runner_can_skip_local_aggregator_start(tmp_path: Path):
    system_settings.config_settings_path = "app_federated.yml"
    aggregator_dir = tmp_path / "aggregator"
    _prepare_participant_dir(aggregator_dir)

    config = FLNetLocalTestConfigDTO(
        aggregator_id="aggregator",
        start_aggregator=False,
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator",
                role="aggregator",
                base_dir=aggregator_dir,
            ),
        ],
    )

    runner = LocalFederatedRunner(config)
    results = runner.run({})

    assert results["aggregator"].success is True
    assert results["aggregator"].result is None

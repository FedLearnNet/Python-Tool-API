"""Tests for the engine-internal aggregator-only dispatch path (WorkerManager + AggregatorOnlyWorker),
covering the platform-as-aggregator case: a real production START_RUN task whose relay config
marks this participant as coordinator and carries no input data at all."""
from pathlib import Path

import numpy as np
import pytest

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.federated import FLNetLocalParticipantConfigDTO, FLNetLocalTestConfigDTO
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.controller.client import FLNetCommunicatorClient
from pyfedappwrap.engine.tests.federated.controller import FLNetInMemoryController
from pyfedappwrap.engine.worker.aggregator_only_worker import (
    AggregatorOnlyWorker,
    extract_round_count,
)
from pyfedappwrap.engine.worker.run_dto import RunStatusTypes
from pyfedappwrap.engine.worker.worker_manager import WorkerManager, is_aggregator_only_task
from tests.apps.federated_aggregator import MeanVectorAggregator


# ---- is_aggregator_only_task -------------------------------------------------------------

def test_is_aggregator_only_task_true_for_coordinator_with_no_data():
    body = {
        "config": {"clientId": "agg-1", "coordinatorId": "agg-1"},
        "inputFilePaths": {},
        "inputData": {},
    }
    assert is_aggregator_only_task(body) is True


def test_is_aggregator_only_task_false_when_coordinator_also_has_data():
    # A coordinator CLINIC that also trains - random-clinic mode - must keep going through the
    # normal registered-app path. This is the key regression guard for existing behavior.
    body = {
        "config": {"clientId": "clinic-1", "coordinatorId": "clinic-1"},
        "inputFilePaths": {"data": "data.csv"},
        "inputData": {},
    }
    assert is_aggregator_only_task(body) is False


def test_is_aggregator_only_task_false_for_plain_client():
    body = {
        "config": {"clientId": "clinic-1", "coordinatorId": "agg-1"},
        "inputFilePaths": {},
        "inputData": {},
    }
    assert is_aggregator_only_task(body) is False


def test_is_aggregator_only_task_false_for_non_federated_app():
    # No "config" at all - a plain (non-federated) app's task body.
    assert is_aggregator_only_task({"inputFilePaths": {}, "inputData": {}}) is False


# ---- extract_round_count ------------------------------------------------------------------

def test_extract_round_count_prefers_top_level_total_rounds():
    assert extract_round_count({"totalRounds": 5, "hyperParams": {"federated_rounds": 99}}) == 5


def test_extract_round_count_falls_back_to_hyper_params():
    assert extract_round_count({"hyperParams": {"federated_rounds": 3}}) == 3
    assert extract_round_count({"hyperParams": {"total_rounds": 7}}) == 7


def test_extract_round_count_defaults_to_one():
    assert extract_round_count({}) == 1


# ---- WorkerManager dispatch -----------------------------------------------------------------

class _FakeWsClient:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)

    def register(self, observer):
        pass


class _FakeApp:
    def __init__(self):
        self.started_with = None

    def set_startup(self, *args, **kwargs):
        self.started_with = args

    def start_app(self):
        pass


def test_start_worker_picks_aggregator_only_worker_for_platform_aggregator_task():
    manager = WorkerManager(_FakeWsClient(), upload_client=None, lifecycle=EngineLifecycle())
    manager.register_aggregator(MeanVectorAggregator(), "mean")
    manager.available_worker = _FakeApp()

    task_body = {
        "id": 1,
        "config": {"clientId": "agg-1", "coordinatorId": "agg-1"},
        "inputFilePaths": {},
        "inputData": {},
    }
    manager.start_worker(1, run_type=None, task_body=task_body)

    assert isinstance(manager.worker, AggregatorOnlyWorker)


def test_start_worker_uses_registered_app_for_coordinator_clinic_with_data():
    manager = WorkerManager(_FakeWsClient(), upload_client=None, lifecycle=EngineLifecycle())
    manager.register_aggregator(MeanVectorAggregator(), "mean")
    fake_app = _FakeApp()
    manager.available_worker = fake_app

    task_body = {
        "id": 1,
        "config": {"clientId": "clinic-1", "coordinatorId": "clinic-1"},
        "inputFilePaths": {"data": "data.csv"},
        "inputData": {},
    }
    manager.start_worker(1, run_type=None, task_body=task_body)

    assert not isinstance(manager.worker, AggregatorOnlyWorker)


def test_register_aggregator_also_wires_plain_worker_manager():
    from pyfedappwrap.engine.runtime import FedDBEngine

    engine = FedDBEngine(test_mode=True)
    aggregator = MeanVectorAggregator()
    engine.register_aggregator(aggregator, "mean")

    assert engine.worker_manager._aggregators.get("mean") is aggregator
    assert engine.federated_worker_manager.get_aggregator("mean") is aggregator


# ---- AggregatorOnlyWorker round loop, against a real FLNetCommunicatorAggregator -----------

def test_run_aggregation_calls_registered_aggregator_and_broadcasts(tmp_path: Path, monkeypatch):
    config = FLNetLocalTestConfigDTO(
        aggregator_id="agg-1",
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="agg-1", role="aggregator", base_dir=tmp_path / "agg",
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1", role="client", base_dir=tmp_path / "c1",
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-2", role="client", base_dir=tmp_path / "c2",
            ),
        ],
    )
    controller = FLNetInMemoryController(config)

    worker = AggregatorOnlyWorker({"mean": MeanVectorAggregator()})
    worker.logger = _NullLogger()

    monkeypatch.setattr(system_settings.fl_run, "controller_comm_url", "http://controller/learning")
    monkeypatch.setattr(system_settings, "app_key", "app-key")
    monkeypatch.setattr(system_settings, "app_api_key", "agg-1")
    monkeypatch.setattr(
        worker, "_build_communicator",
        lambda body: _build_test_communicator(controller, config),
    )

    client_1 = FLNetCommunicatorClient(
        "http://controller/learning", "app-key", controller_app_key="client-1",
        client_id="client-1", client_ids=[], aggregator_id="agg-1", channel="local-test",
        session=controller.build_session("client-1"),
    )
    client_2 = FLNetCommunicatorClient(
        "http://controller/learning", "app-key", controller_app_key="client-2",
        client_id="client-2", client_ids=[], aggregator_id="agg-1", channel="local-test",
        session=controller.build_session("client-2"),
    )
    client_1.send_data_to_aggregator(np.array([1.0, 3.0]), aggregator_name="mean", communication_id="round-1")
    client_2.send_data_to_aggregator(np.array([3.0, 5.0]), aggregator_name="mean", communication_id="round-1")

    worker._run_aggregation({"config": {}, "totalRounds": 1})

    result = client_1.await_data_from_aggregator("mean", communication_id="round-1")
    assert np.array_equal(result.data, np.array([2.0, 4.0]))


# ---- _build_communicator -----------------------------------------------------------------

def test_build_communicator_uses_the_relay_registered_app_key_not_the_tool_api_key(monkeypatch):
    # The Controller run was registered (via /start-learning) with this participant's relay id
    # as its appKey (see ProjectFederatedExperimentAggregatorBO.startControllerLearning), not
    # with this tool's static app_api_key. Using app_api_key here makes every FL controller HTTP
    # request address a run key the Controller never registered - a 404 "no such run key".
    monkeypatch.setattr(system_settings.fl_run, "controller_comm_url", "http://controller/learning")
    monkeypatch.setattr(system_settings, "app_key", "tool-app-key")
    monkeypatch.setattr(system_settings, "app_api_key", "tool-api-key")

    worker = AggregatorOnlyWorker({})
    communicator = worker._build_communicator({
        "config": {
            "channel": "channel-1",
            "coordinatorId": "relay-id-1",
            "clientId": "relay-id-1",
            "orderClientIds": ["relay-id-2", "relay-id-3"],
        }
    })

    assert communicator.controller_app_key == "relay-id-1"
    assert communicator.aggregator_id == "relay-id-1"
    assert communicator.app_key == "tool-app-key"
    assert communicator.channel == "channel-1"


def _build_test_communicator(controller, config):
    from pyfedappwrap.engine.service.controller.aggregator import FLNetCommunicatorAggregator
    return FLNetCommunicatorAggregator(
        "http://controller/learning", "app-key", controller_app_key="agg-1",
        client_id="agg-1", client_ids=["client-1", "client-2"], aggregator_id="agg-1",
        channel="local-test", session=controller.build_session("agg-1"), timeout=0.5, max_polls=5,
        aggregators={"mean": MeanVectorAggregator()},
    )


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

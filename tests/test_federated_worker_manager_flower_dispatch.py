"""The START_FEDERATED_RUN dispatch split Julian approved: same message, same entry point,
routed to _start_federated_run_flower vs _start_federated_run_flnet by communicationEngine."""
from typing import Any

import pytest

from pyfedappwrap.engine.enums.test_embed_states import RunType
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.socket.messages.federated import FederatedTestRunCreateDTO
from pyfedappwrap.engine.worker import federated_worker_manager
from pyfedappwrap.engine.worker.federated_worker_manager import FederatedWorkerManager
from pyfedappwrap.learning.federated.flower_app import FlowerApp


class _RecordingWsClient:
    def __init__(self):
        self.messages = []

    def register(self, observer):
        pass

    def send(self, message):
        self.messages.append(message)

    def statuses(self) -> list[str]:
        return [m.message.status for m in self.messages]


class _FakeFlowerRunLifecycle:
    instances: list["_FakeFlowerRunLifecycle"] = []

    def __init__(self, flower_app):
        self.flower_app = flower_app
        self.aggregator_result: tuple[bool, Any] = (True, None)
        self.client_calls: list[dict] = []
        self.report_running_was_called = False
        _FakeFlowerRunLifecycle.instances.append(self)

    def run_as_aggregator(self, *, report_running=None, **kwargs):
        if report_running:
            report_running()
            self.report_running_was_called = True
        return self.aggregator_result

    def start_as_client(self, **kwargs):
        self.client_calls.append(kwargs)


@pytest.fixture(autouse=True)
def fake_lifecycle(monkeypatch):
    _FakeFlowerRunLifecycle.instances = []
    monkeypatch.setattr(federated_worker_manager, "FlowerRunLifecycle", _FakeFlowerRunLifecycle)
    yield _FakeFlowerRunLifecycle


def make_manager(ws_client=None, flower_app=None):
    manager = FederatedWorkerManager(ws_client or _RecordingWsClient(), EngineLifecycle())
    manager.available_flower_app = flower_app if flower_app is not None else FlowerApp()
    return manager


def aggregator_run_dto(**overrides):
    payload = {
        "id": 1,
        "communicationEngine": "FLOWER",
        "participants": [{"participantId": "platform", "role": "AGGREGATOR"}],
    }
    payload.update(overrides)
    return FederatedTestRunCreateDTO.model_validate(payload)


def client_run_dto(**overrides):
    payload = {
        "id": 2,
        "communicationEngine": "FLOWER",
        "participants": [{"participantId": "clinic-1", "role": "CLIENT"}],
        "config": {"superlinkAddress": "platform.example:8000"},
    }
    payload.update(overrides)
    return FederatedTestRunCreateDTO.model_validate(payload)


def test_a_flower_tagged_aggregator_run_starts_the_superlink_and_reports_finished():
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client)

    manager._start_federated_run_flower(aggregator_run_dto(), RunType.FEDERATED_RUN)

    assert ws_client.statuses() == ["STARTED", "RUNNING", "FINISHED"]
    assert _FakeFlowerRunLifecycle.instances[0].report_running_was_called
    assert manager._flower_lifecycles == {}


def test_an_aggregator_run_that_fails_reports_error_with_the_failure_reason():
    manager = make_manager()
    _FakeFlowerRunLifecycle.instances  # ensure list exists before monkeypatch instantiation
    ws_client = manager.ws_client

    def failing_init(flower_app):
        lc = _FakeFlowerRunLifecycle(flower_app)
        lc.aggregator_result = (False, "No heartbeat received from the task")
        return lc

    import pyfedappwrap.engine.worker.federated_worker_manager as m
    m.FlowerRunLifecycle = failing_init

    manager._start_federated_run_flower(aggregator_run_dto(), RunType.FEDERATED_RUN)

    finish = ws_client.messages[-1].message
    assert finish.status == "ERROR"
    assert finish.error == "No heartbeat received from the task"


def test_a_flower_tagged_client_run_starts_the_supernode_and_keeps_its_lifecycle_registered():
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client)

    manager._start_federated_run_flower(client_run_dto(), RunType.FEDERATED_RUN)

    assert ws_client.statuses() == ["STARTED", "RUNNING"]
    lifecycle = _FakeFlowerRunLifecycle.instances[0]
    assert lifecycle.client_calls == [{
        "superlink_address": "platform.example:8000",
        "root_certificates": None,
        "auth_private_key": None,
    }]
    assert manager._flower_lifecycles[2] is lifecycle


def test_a_client_run_with_no_provisioned_superlink_address_reports_error():
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client)

    manager._start_federated_run_flower(client_run_dto(config={}), RunType.FEDERATED_RUN)

    finish = ws_client.messages[-1].message
    assert finish.status == "ERROR"
    assert "superlink_address" in finish.error.lower() or "superlinkaddress" in finish.error.lower() \
        or "SuperLink address" in finish.error
    assert manager._flower_lifecycles == {}


def test_no_flower_app_registered_reports_error():
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client, flower_app=None)
    manager.available_flower_app = None

    manager._start_federated_run_flower(aggregator_run_dto(), RunType.FEDERATED_RUN)

    assert ws_client.statuses() == ["STARTED", "ERROR"]


def test_more_or_fewer_than_one_participant_reports_error():
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client)
    run_dto = aggregator_run_dto(participants=[
        {"participantId": "platform", "role": "AGGREGATOR"},
        {"participantId": "clinic-1", "role": "CLIENT"},
    ])

    manager._start_federated_run_flower(run_dto, RunType.FEDERATED_RUN)

    finish = ws_client.messages[-1].message
    assert finish.status == "ERROR"
    assert "exactly one participant" in finish.error


def test_the_default_communication_engine_still_routes_to_the_fl_net_path(monkeypatch):
    """Backward compatibility: a message with no communicationEngine field at all (every
    existing FL-Net tool/sender) must still take the FL-Net path, never the Flower one."""
    calls = []
    monkeypatch.setattr(FederatedWorkerManager, "_start_federated_run_flnet",
                        lambda self, *a, **k: calls.append(("flnet", a, k)))
    monkeypatch.setattr(FederatedWorkerManager, "_start_federated_run_flower",
                        lambda self, *a, **k: calls.append(("flower", a, k)))
    manager = make_manager()
    manager.upload_client = None

    message = {"id": 99, "participants": [{"participantId": "p", "role": "AGGREGATOR"}]}
    manager._handle_start(message, run_type=RunType.FEDERATED_RUN)

    assert len(calls) == 1
    assert calls[0][0] == "flnet"

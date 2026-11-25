"""The START_FEDERATED_RUN dispatch split Julian approved: same message, same entry point,
routed to _start_federated_run_flower vs _start_federated_run_flnet by communicationEngine."""
import time
from unittest.mock import Mock
from typing import Any

import pytest

from pyfedappwrap.engine.enums.test_embed_states import RunType, WebsocketMessageTypes
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.service.socket.messages.federated import FederatedTestRunCreateDTO
from pyfedappwrap.engine.worker import federated_worker_manager
from pyfedappwrap.engine.worker.federated_worker_manager import FederatedWorkerManager
from pyfedappwrap.learning.federated.flower_app import FlowerApp


class _RecordingWsClient:
    def __init__(self):
        self.messages = []
        self.manager = None
        # (success, error) answers the "platform" gives to SuperNode key requests, in order;
        # None leaves a request unanswered.
        self.registration_answers: list = []

    def register(self, observer):
        pass

    def send(self, message):
        self.messages.append(message)
        if message.type == WebsocketMessageTypes.FLOWER_SUPERNODE_KEY and self.registration_answers:
            answer = self.registration_answers.pop(0)
            if answer is not None:
                success, error = answer
                self.manager._on_supernode_registered({
                    "requestId": message.message.request_id, "success": success, "error": error})

    def statuses(self) -> list[str]:
        return [m.message.status for m in self.messages if hasattr(m.message, "status")]

    def of_type(self, message_type) -> list:
        return [m.message for m in self.messages if m.type == message_type]


class _FakeFlowerRunLifecycle:
    instances: list["_FakeFlowerRunLifecycle"] = []

    def __init__(self, flower_app):
        self.flower_app = flower_app
        self.aggregator_result: tuple[bool, Any] = (True, None)
        self.client_calls: list[dict] = []
        self.report_running_was_called = False
        self.aggregator_kwargs: dict = {}
        self.registered: list = []
        self.register_error = None
        self.saved_model = None
        _FakeFlowerRunLifecycle.instances.append(self)

    def saved_model_path(self):
        return self.saved_model

    def run_as_aggregator(self, *, report_running=None, **kwargs):
        self.aggregator_kwargs = kwargs
        if report_running:
            report_running()
            self.report_running_was_called = True
        return self.aggregator_result

    def start_as_client(self, **kwargs):
        self.client_calls.append(kwargs)

    def register_supernode(self, public_key, *, name=None):
        self.registered.append((public_key, name))
        if self.register_error:
            raise self.register_error


@pytest.fixture(autouse=True)
def fake_lifecycle(monkeypatch):
    _FakeFlowerRunLifecycle.instances = []
    monkeypatch.setattr(federated_worker_manager, "FlowerRunLifecycle", _FakeFlowerRunLifecycle)
    yield _FakeFlowerRunLifecycle


def make_manager(ws_client=None, flower_app=None):
    ws_client = ws_client or _RecordingWsClient()
    manager = FederatedWorkerManager(ws_client, EngineLifecycle())
    ws_client.manager = manager
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

    # No stored CA yet (first run): one RUNNING update reports the newly generated CA, right
    # after STARTED and before the SuperLink itself reports running.
    assert ws_client.statuses() == ["STARTED", "RUNNING", "RUNNING", "FINISHED"]
    assert _FakeFlowerRunLifecycle.instances[0].report_running_was_called
    assert manager._flower_lifecycles == {}


def test_an_aggregator_run_reports_its_freshly_generated_ca_certificate():
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client)

    manager._start_federated_run_flower(aggregator_run_dto(), RunType.FEDERATED_RUN)

    reports = [m.message for m in ws_client.messages if m.message.ca_certificate]
    assert len(reports) == 1
    assert "BEGIN CERTIFICATE" in reports[0].ca_certificate
    assert "BEGIN PRIVATE KEY" in reports[0].ca_private_key


def test_an_aggregator_run_reuses_the_stored_ca_and_does_not_report_it_again(tmp_path):
    from pyfedappwrap.engine.service.flower import certs
    cert_pem, key_pem = certs._pem_pair(*certs._self_signed_ca())
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client)

    manager._start_federated_run_flower(aggregator_run_dto(config={
        "caCertificate": cert_pem, "caPrivateKey": key_pem,
    }), RunType.FEDERATED_RUN)

    assert [m.message.ca_certificate for m in ws_client.messages if m.message.ca_certificate] == []
    assert ws_client.statuses() == ["STARTED", "RUNNING", "FINISHED"]
    ca_path = _FakeFlowerRunLifecycle.instances[0].aggregator_kwargs["ssl_ca_certfile"]
    assert ca_path.read_text() == cert_pem


def test_an_aggregator_run_with_a_stored_ca_passes_tls_cert_paths_to_run_as_aggregator():
    from pyfedappwrap.engine.service.flower import certs
    cert_pem, key_pem = certs._pem_pair(*certs._self_signed_ca())
    manager = make_manager(_RecordingWsClient())

    manager._start_federated_run_flower(aggregator_run_dto(config={
        "caCertificate": cert_pem, "caPrivateKey": key_pem,
    }), RunType.FEDERATED_RUN)

    lifecycle = _FakeFlowerRunLifecycle.instances[0]
    assert lifecycle.aggregator_kwargs["ssl_certfile"].name == "server.pem"
    assert lifecycle.aggregator_kwargs["ssl_keyfile"].name == "server.key"
    assert lifecycle.aggregator_kwargs["ssl_ca_certfile"].name == "ca.crt"


def test_the_first_aggregator_run_without_a_stored_ca_runs_insecure():
    manager = make_manager(_RecordingWsClient())

    manager._start_federated_run_flower(aggregator_run_dto(), RunType.FEDERATED_RUN)

    kwargs = _FakeFlowerRunLifecycle.instances[0].aggregator_kwargs
    assert kwargs["ssl_certfile"] is None
    assert kwargs["ssl_keyfile"] is None
    assert kwargs["ssl_ca_certfile"] is None


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


def test_a_client_run_with_a_provisioned_ca_certificate_writes_it_locally_and_uses_it():
    ws_client = _RecordingWsClient()
    ws_client.registration_answers = [(True, None)]
    manager = make_manager(ws_client)
    run_dto = client_run_dto(config={
        "superlinkAddress": "platform.example:8000",
        "caCertificate": "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n",
    })

    manager._start_federated_run_flower(run_dto, RunType.FEDERATED_RUN)

    lifecycle = _FakeFlowerRunLifecycle.instances[0]
    [call] = lifecycle.client_calls
    assert call["root_certificates"].name == "ca.crt"
    assert call["root_certificates"].read_text() == run_dto.config.ca_certificate


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


CA_PEM = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"


def tls_client_run_dto():
    return client_run_dto(config={"superlinkAddress": "platform.example:8000", "caCertificate": CA_PEM})


@pytest.fixture
def fast_registration(monkeypatch):
    monkeypatch.setattr(federated_worker_manager, "SUPERNODE_REGISTRATION_RETRY_SECONDS", 0.01)
    monkeypatch.setattr(federated_worker_manager, "SUPERNODE_REGISTRATION_TIMEOUT_SECONDS", 0.5)


def test_a_tls_client_registers_its_supernode_key_before_starting_and_uses_its_private_key():
    ws_client = _RecordingWsClient()
    ws_client.registration_answers = [(True, None)]
    manager = make_manager(ws_client)

    manager._start_federated_run_flower(tls_client_run_dto(), RunType.FEDERATED_RUN)

    [request] = ws_client.of_type(WebsocketMessageTypes.FLOWER_SUPERNODE_KEY)
    assert request.public_key.startswith("ecdsa-sha2-nistp384 ")
    [call] = _FakeFlowerRunLifecycle.instances[0].client_calls
    assert b"OPENSSH PRIVATE KEY" in call["auth_private_key"].read_bytes()
    assert ws_client.statuses() == ["STARTED", "RUNNING"]
    assert manager._pending_registrations == {}


def test_a_tls_client_keeps_asking_while_the_aggregator_is_not_ready(fast_registration):
    ws_client = _RecordingWsClient()
    ws_client.registration_answers = [(False, "The SuperLink of this run is not running yet"),
                                      None, (True, None)]
    manager = make_manager(ws_client)

    manager._start_federated_run_flower(tls_client_run_dto(), RunType.FEDERATED_RUN)

    requests = ws_client.of_type(WebsocketMessageTypes.FLOWER_SUPERNODE_KEY)
    assert len(requests) == 3
    # One request id for the whole registration, so a late answer still matches.
    assert len({r.request_id for r in requests}) == 1
    assert _FakeFlowerRunLifecycle.instances[0].client_calls[0]["auth_private_key"] is not None


def test_a_tls_client_that_is_never_registered_fails_without_starting_its_supernode(fast_registration):
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client)

    manager._start_federated_run_flower(tls_client_run_dto(), RunType.FEDERATED_RUN)

    assert _FakeFlowerRunLifecycle.instances[0].client_calls == []
    assert ws_client.statuses() == ["STARTED", "ERROR"]
    assert "not registered" in ws_client.messages[-1].message.error
    assert manager._flower_lifecycles == {}


def test_a_client_without_a_ca_certificate_skips_registration():
    """First run on a fresh platform: no CA yet, so the SuperLink runs insecure without auth."""
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client)

    manager._start_federated_run_flower(client_run_dto(), RunType.FEDERATED_RUN)

    assert ws_client.of_type(WebsocketMessageTypes.FLOWER_SUPERNODE_KEY) == []
    [call] = _FakeFlowerRunLifecycle.instances[0].client_calls
    assert call["auth_private_key"] is None


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def test_the_aggregator_registers_a_clinic_key_and_answers_success():
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client)
    aggregator = _FakeFlowerRunLifecycle(FlowerApp())
    manager._flower_aggregator = aggregator

    manager.update(_event(WebsocketMessageTypes.FLOWER_SUPERNODE_KEY, {
        "requestId": "r1", "publicKey": "ecdsa-sha2-nistp384 AAAA", "name": "clinic-1"}))

    _wait_for(lambda: ws_client.of_type(WebsocketMessageTypes.FLOWER_SUPERNODE_REGISTERED))
    [answer] = ws_client.of_type(WebsocketMessageTypes.FLOWER_SUPERNODE_REGISTERED)
    assert (answer.request_id, answer.success) == ("r1", True)
    assert aggregator.registered == [("ecdsa-sha2-nistp384 AAAA", "clinic-1")]


def test_the_aggregator_answers_failure_while_no_superlink_is_running():
    ws_client = _RecordingWsClient()
    manager = make_manager(ws_client)

    manager.update(_event(WebsocketMessageTypes.FLOWER_SUPERNODE_KEY, {
        "requestId": "r1", "publicKey": "ecdsa-sha2-nistp384 AAAA"}))

    _wait_for(lambda: ws_client.of_type(WebsocketMessageTypes.FLOWER_SUPERNODE_REGISTERED))
    [answer] = ws_client.of_type(WebsocketMessageTypes.FLOWER_SUPERNODE_REGISTERED)
    assert answer.success is False
    assert answer.error


def _event(message_type, message):
    return BaseSocketMessage.model_validate({
        "type": message_type.value, "runType": "FEDERATED_RUN", "message": message})


# --- Uploading the aggregator's model (#11 Task 6) ---

class _RecordingUploadClient:
    def __init__(self, error=None):
        self.uploads: list[dict] = []
        self.error = error

    def upload_model_file(self, *, run_id, name, file_path):
        if self.error:
            raise self.error
        self.uploads.append({"run_id": run_id, "name": name, "file_path": file_path})


def _aggregator_saving(path):
    def init(flower_app):
        lc = _FakeFlowerRunLifecycle(flower_app)
        lc.saved_model = path
        return lc
    return init


def test_the_aggregator_uploads_the_saved_model_before_reporting_finished(monkeypatch, tmp_path):
    model = tmp_path / "final_model.npz"
    monkeypatch.setattr(federated_worker_manager, "FlowerRunLifecycle", _aggregator_saving(model))
    manager = make_manager()
    upload_client = _RecordingUploadClient()

    manager._start_federated_run_flower(aggregator_run_dto(), RunType.FEDERATED_RUN, upload_client)

    assert upload_client.uploads == [{"run_id": 1, "name": "final_model.npz", "file_path": str(model)}]
    assert manager.ws_client.statuses()[-1] == "FINISHED"


def test_a_failed_model_upload_fails_the_aggregator_run(monkeypatch, tmp_path):
    model = tmp_path / "final_model.npz"
    monkeypatch.setattr(federated_worker_manager, "FlowerRunLifecycle", _aggregator_saving(model))
    manager = make_manager()

    manager._start_federated_run_flower(aggregator_run_dto(), RunType.FEDERATED_RUN,
                                        _RecordingUploadClient(error=ConnectionError("refused")))

    finish = manager.ws_client.messages[-1].message
    assert finish.status == "ERROR"
    assert "final_model.npz" in finish.error and "refused" in finish.error


def test_an_aggregator_run_without_a_saved_model_uploads_nothing():
    manager = make_manager()
    upload_client = _RecordingUploadClient()

    manager._start_federated_run_flower(aggregator_run_dto(), RunType.FEDERATED_RUN, upload_client)

    assert upload_client.uploads == []
    assert manager.ws_client.statuses()[-1] == "FINISHED"


def test_a_flower_start_message_hands_the_execution_upload_client_to_the_flower_path(monkeypatch):
    manager = make_manager()
    scoped = _RecordingUploadClient()
    manager.upload_client = Mock(for_execution=Mock(return_value=scoped))
    started = []
    monkeypatch.setattr(manager, "_start_federated_run_flower",
                        lambda run_dto, run_type, upload_client: started.append(upload_client))

    manager._handle_start(aggregator_run_dto().model_dump(by_alias=True), run_type=RunType.FEDERATED_RUN)
    for thread in list(manager._active_runs.values()):
        thread.join(timeout=5)

    assert started == [scoped]

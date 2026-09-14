from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import numpy as np
import pytest

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import TestEmbedEnum as EmbedEventType
from pyfedappwrap.engine.enums.test_embed_states import RunType
from pyfedappwrap.engine.federated import (
    AppAggregator,
    FLNetDataPackageDTO,
    FLNetLocalParticipantConfigDTO,
    FLNetLocalTestConfigDTO,
    FLNetMessageMetaDTO,
    FLNetSerializer,
)
from pyfedappwrap.engine.tests.federated.controller import FLNetInMemoryController
from pyfedappwrap.engine.observer.subject import Subject
from pyfedappwrap.engine.runtime import FedDBEngine
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.controller.aggregator import FLNetCommunicatorAggregator
from pyfedappwrap.engine.service.controller.client import FLNetCommunicatorClient
from pyfedappwrap.engine.worker.federated_worker_manager import FederatedWorkerManager


@dataclass
class ModelWeights:
    weights: np.ndarray = None


class FakeResponse:
    def __init__(self, status_code: int, payload: Any = None):
        self.status_code = status_code
        self._payload = payload
        self.content = b"" if payload is None else b"payload"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, json: dict[str, Any] = None, data: Any = None, files: Any = None, timeout: float = None, **kwargs):
        self.calls.append({
            "url": url,
            "json": json,
            "data": data,
            "files": files,
            "timeout": timeout,
            "kwargs": kwargs,
        })
        return self.responses.pop(0)


class MeanAggregator(AppAggregator):
    def aggregate(self, data: list[Any], n_clients: int,
                  meta: Optional[FLNetMessageMetaDTO] = None) -> np.ndarray:
        stacked = np.stack(data)
        return np.mean(stacked, axis=0)


def test_federated_worker_manager_consumes_start_federated_test_run():
    subject = Subject()
    manager = FederatedWorkerManager(subject, EngineLifecycle())
    called: dict[str, Any] = {}

    def _capture(message, *, run_type):
        called["message"] = message
        called["run_type"] = run_type

    manager._handle_start = _capture
    event = SimpleNamespace(
        type="START_FEDERATED_RUN",
        message={"id": 123},
        run_type="FEDERATED_TEST_RUN",
    )

    manager.update(event)

    assert called["message"] == {"id": 123}
    assert called["run_type"] == RunType.FEDERATED_TEST_RUN


def test_federated_worker_manager_treats_explicit_test_event_as_test_run():
    subject = Subject()
    manager = FederatedWorkerManager(subject, EngineLifecycle())
    called: dict[str, Any] = {}

    def _capture(message, *, run_type):
        called["message"] = message
        called["run_type"] = run_type

    manager._handle_start = _capture
    event = SimpleNamespace(
        type=EmbedEventType.START_FEDERATED_TEST_RUN,
        message={"id": 123},
        run_type=RunType.FEDERATED_RUN,
    )

    manager.update(event)

    assert called["message"] == {"id": 123}
    assert called["run_type"] == RunType.FEDERATED_TEST_RUN


def test_federated_test_event_includes_coordinator_input_file_paths():
    from pyfedappwrap.engine.tests.events import TestEvents

    events = TestEvents.__new__(TestEvents)
    events.get_hyperparams = lambda: {"federated_rounds": 1}
    events.get_federated_input_files = lambda: {"data": "input.csv"}

    event = events.default_start_federated_test_run_task()

    assert event.run_type == RunType.FEDERATED_TEST_RUN
    assert event.message["participants"][0]["participantId"] == "aggregator"
    assert event.message["participants"][0]["inputFilePaths"] == {"data": "input.csv"}


def test_serializer_round_trips_dataclass_with_numpy_array():
    serializer = FLNetSerializer()
    model = ModelWeights(weights=np.array([1.0, 2.0, 3.0]))

    payload = serializer.serialize(model)
    restored = serializer.deserialize(payload, ModelWeights)

    assert isinstance(restored, ModelWeights)
    assert np.array_equal(restored.weights, model.weights)


def test_client_send_data_to_aggregator_uses_controller_contract():
    session = FakeSession([FakeResponse(200, {"communication_id": "round-7"})])
    client = FLNetCommunicatorClient(
        "http://controller/learning",
        "app-key",
        controller_app_key="client-1",
        client_id="client-1",
        client_ids=[],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=session,
    )

    communication_id = client.send_data_to_aggregator(
        {"weights": [1, 2, 3]},
        aggregator_name="aggregator-1",
        communication_id="round-7",
    )

    assert communication_id == "round-7"
    assert session.calls[0]["url"] == "http://controller/learning/send-data-to-aggregator"
    metadata = json.loads(session.calls[0]["files"]["metadata"][1])
    assert metadata["toAggregator"] == "aggregator-1"
    assert metadata["communicationId"] == "round-7"
    assert metadata["appKey"] == "client-1"


def test_client_send_uses_default_smpc_settings_when_enabled():
    session = FakeSession([FakeResponse(200, {"communication_id": "round-8"})])
    client = FLNetCommunicatorClient(
        "http://controller/learning",
        "app-key",
        controller_app_key="client-1",
        client_id="client-1",
        client_ids=[],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=session,
    )

    previous_enabled = system_settings.smpc.enabled
    previous_use_smpc = system_settings.smpc.use_smpc
    previous_exponent = system_settings.smpc.exponent
    previous_num_shards = system_settings.smpc.num_shards
    previous_operation = system_settings.smpc.operation

    try:
        system_settings.smpc.enabled = True
        system_settings.smpc.use_smpc = True
        system_settings.smpc.exponent = 12
        system_settings.smpc.num_shards = 3
        system_settings.smpc.operation = "add"

        client.send_data_to_aggregator({"weights": [1, 2, 3]}, aggregator_name="aggregator-1", communication_id="round-8")
    finally:
        system_settings.smpc.enabled = previous_enabled
        system_settings.smpc.use_smpc = previous_use_smpc
        system_settings.smpc.exponent = previous_exponent
        system_settings.smpc.num_shards = previous_num_shards
        system_settings.smpc.operation = previous_operation

    metadata_json = session.calls[0]["files"]["metadata"][1]
    metadata_dict = json.loads(metadata_json)
    assert metadata_dict["smpc"]["useSmpc"] is True
    assert metadata_dict["smpc"]["exponent"] == 12
    assert metadata_dict["smpc"]["numShards"] == 3


def test_client_aggregate_wraps_send_and_await():
    serializer = FLNetSerializer()
    session = FakeSession([
        FakeResponse(200, {"communication_id": "default-1"}),
        FakeResponse(200, {
            "from": "aggregator-1",
            "communication_id": "default-1",
            "data": serializer.serialize(ModelWeights(weights=np.array([4.0, 5.0]))),
            "meta": serializer.serialize(FLNetMessageMetaDTO(**{"communicationId": "default-1", "fromClientId": "aggregator-1", "fromAggregator": "aggregator-1"})),
        }),
    ])
    client = FLNetCommunicatorClient(
        "http://controller/learning",
        "app-key",
        controller_app_key="client-1",
        client_id="client-1",
        client_ids=[],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=session,
        poll_interval=0.0,
        max_polls=1,
    )

    package = client.aggregate(
        ModelWeights(weights=np.array([1.0, 2.0])),
        aggregator_name="aggregator-1",
        data_type=ModelWeights,
    )

    assert package.sender == "aggregator-1"
    assert package.communication_id == "default-1"
    assert isinstance(package.data, ModelWeights)
    assert np.array_equal(package.data.weights, np.array([4.0, 5.0]))


def test_aggregator_can_await_client_packages():
    serializer = FLNetSerializer()
    session = FakeSession([
        FakeResponse(200, {'round-1': [
            {
                "from": "client-1",
                "communication_id": "round-1",
                "data": serializer.serialize(np.array([1.0, 3.0])),
                "meta": {"communicationId": "round-1", "fromClientId": "client-1", "toAggregator": "aggregator-1", "timeArrived": "2023-01-01T00:00:00Z"},
            },
            {
                "from": "client-2",
                "communication_id": "round-1",
                "data": serializer.serialize(np.array([3.0, 5.0])),
                "meta": {"communicationId": "round-1", "fromClientId": "client-2", "toAggregator": "aggregator-1", "timeArrived": "2023-01-01T00:00:00Z"},
            },
        ]}),
    ])
    communicator = FLNetCommunicatorAggregator(
        "http://controller/learning",
        "app-key",
        controller_app_key="aggregator-1",
        client_id="aggregator-1",
        client_ids=["client-1", "client-2"],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=session,
        poll_interval=0.0,
        max_polls=1,
    )

    grouped_packages = communicator.await_data_from_clients(
        num_data_packages_per_communication_round=2,
        to_aggregator="aggregator-1",
        communication_id="round-1",
        data_type=np.ndarray,
    )

    packages = grouped_packages["round-1"]
    assert isinstance(packages[0], FLNetDataPackageDTO)
    assert len(packages) == 2

def test_engine_register_aggregator_applies_existing_registry_to_federated_runtime():
    engine = FedDBEngine(test_mode=True)
    engine.register_aggregator(MeanAggregator(), "default")
    assert engine.federated_worker_manager.get_aggregator("default") is not None


def test_engine_register_aggregator_updates_already_registered_federated_runtime():
    engine = FedDBEngine(test_mode=True)
    engine.register_aggregator(MeanAggregator(), "late")
    assert engine.federated_worker_manager.get_aggregator("late") is not None


def test_federated_worker_distinguishes_test_simulation_from_real_run(monkeypatch):
    monkeypatch.setattr(system_settings.fl_run, "controller_comm_url", "http://controller.local")
    participants = [
        FLNetLocalParticipantConfigDTO(
            participant_id="aggregator",
            role="AGGREGATOR",
            base_dir=Path("."),
        ),
        FLNetLocalParticipantConfigDTO(
            participant_id="env-app-id",
            role="CLIENT",
            base_dir=Path("."),
        ),
    ]
    run_dto = SimpleNamespace(
        config=SimpleNamespace(
            poll_interval=None,
            timeout=None,
            max_polls=None,
            channel=None,
        ),
        start_aggregator=None,
    )

    previous = system_settings.fl_test.use_dockerized_controller
    try:
        system_settings.fl_test.use_dockerized_controller = False
        test_config = FederatedWorkerManager._build_run_config(
            run_dto,
            participants,
            run_type=RunType.FEDERATED_TEST_RUN,
        )
        real_config = FederatedWorkerManager._build_run_config(
            run_dto,
            participants,
            run_type=RunType.FEDERATED_RUN,
        )
    finally:
        system_settings.fl_test.use_dockerized_controller = previous

    assert test_config.simulate_participants_locally is True
    assert test_config.use_external_controller is False
    assert real_config.simulate_participants_locally is False
    assert real_config.use_external_controller is True
    assert real_config.controller_url == "http://controller.local"
    assert real_config.simulate_participants_locally is False


def test_federated_test_run_uses_dockerized_controller_when_setting_enabled():
    participants = [
        FLNetLocalParticipantConfigDTO(
            participant_id="aggregator",
            role="AGGREGATOR",
            base_dir=Path("."),
        ),
        FLNetLocalParticipantConfigDTO(
            participant_id="client-1",
            role="CLIENT",
            base_dir=Path("."),
        ),
    ]
    run_dto = SimpleNamespace(
        config=SimpleNamespace(
            poll_interval=None,
            timeout=None,
            max_polls=None,
            channel=None,
        ),
        start_aggregator=None,
    )

    previous = system_settings.fl_test.use_dockerized_controller
    try:
        system_settings.fl_test.use_dockerized_controller = True
        config = FederatedWorkerManager._build_run_config(
            run_dto,
            participants,
            run_type=RunType.FEDERATED_TEST_RUN,
        )
    finally:
        system_settings.fl_test.use_dockerized_controller = previous

    assert config.simulate_participants_locally is True
    assert config.use_external_controller is True
    assert config.controller_url == system_settings.fl_test.dockerized_controller_comm_url.rstrip("/")


def test_real_run_without_controller_url_does_not_fallback_to_dockerized_controller(monkeypatch):
    monkeypatch.setattr(system_settings.fl_run, "controller_comm_url", None)
    participants = [
        FLNetLocalParticipantConfigDTO(
            participant_id="aggregator",
            role="AGGREGATOR",
            base_dir=Path("."),
        ),
        FLNetLocalParticipantConfigDTO(
            participant_id="env-app-id",
            role="CLIENT",
            base_dir=Path("."),
        ),
    ]
    run_dto = SimpleNamespace(
        config=SimpleNamespace(
            poll_interval=None,
            timeout=None,
            max_polls=None,
            channel=None,
        ),
        start_aggregator=None,
    )

    with pytest.raises(ValueError, match="Set FL_RUN__CONTROLLER_COMM_URL"):
        FederatedWorkerManager._build_run_config(
            run_dto,
            participants,
            run_type=RunType.FEDERATED_RUN,
        )


def test_external_runner_requires_controller_url_instead_of_guessing_localhost():
    from pyfedappwrap.engine.tests.federated.runner import LocalFederatedRunner

    config = FLNetLocalTestConfigDTO(
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator",
                role="AGGREGATOR",
                base_dir=Path("."),
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1",
                role="CLIENT",
                base_dir=Path("."),
            ),
        ],
        use_external_controller=True,
        simulate_participants_locally=True,
    )
    runner = LocalFederatedRunner(config)

    try:
        runner._controller_url()
    except ValueError as exc:
        assert "External federated runs require a controller URL" in str(exc)
    else:
        raise AssertionError("Expected external runner to require an explicit controller URL")


def test_real_runner_refuses_to_simulate_all_participants_without_app_id_match():
    from pyfedappwrap.engine.tests.federated.runner import LocalFederatedRunner

    previous_app_id = system_settings.app_id
    config = FLNetLocalTestConfigDTO(
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator",
                role="AGGREGATOR",
                base_dir=Path("."),
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1",
                role="CLIENT",
                base_dir=Path("."),
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-2",
                role="CLIENT",
                base_dir=Path("."),
            ),
        ],
        use_external_controller=True,
        simulate_participants_locally=False,
    )
    runner = LocalFederatedRunner(config)

    try:
        system_settings.app_id = "unmatched-app"
        runner.run({})
    except ValueError as exc:
        assert "participantId matching system_settings.app_id" in str(exc)
    else:
        raise AssertionError("Expected real runner to reject ambiguous multi-participant payload")
    finally:
        system_settings.app_id = previous_app_id


# --- Regression tests for serializer / communicator fixes ---------------------


def test_serializer_round_trips_dataclass_with_postponed_annotations():
    """PEP 563 forward refs must be resolved so nested typed fields deserialize."""
    from tests.apps._forward_ref_dataclasses import OuterWithNestedNdarray

    serializer = FLNetSerializer()
    model = OuterWithNestedNdarray(
        name="weights",
        vector=np.array([1.5, 2.5, 3.5]),
    )

    payload = serializer.serialize(model)
    restored = serializer.deserialize(payload, OuterWithNestedNdarray)

    assert isinstance(restored, OuterWithNestedNdarray)
    assert restored.name == "weights"
    assert isinstance(restored.vector, np.ndarray)
    assert np.array_equal(restored.vector, model.vector)


def test_await_data_times_out_without_trailing_sleep():
    import time as _time

    session = FakeSession([FakeResponse(204)])
    communicator = FLNetCommunicatorAggregator(
        "http://controller/learning",
        "app-key",
        controller_app_key="aggregator-1",
        client_id="aggregator-1",
        client_ids=[],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=session,
        timeout=0.05,
        max_polls=3,
    )

    start = _time.monotonic()
    try:
        communicator.await_data_from_clients(num_data_packages_per_communication_round=1)
    except TimeoutError:
        pass
    else:
        raise AssertionError("Expected TimeoutError")
    elapsed = _time.monotonic() - start
    assert elapsed < 0.12, f"await_data waited longer than its timeout (elapsed={elapsed:.3f}s)"
    assert len(session.calls) == 1


def test_await_data_accumulates_partial_results_across_notices():
    config = FLNetLocalTestConfigDTO(
        aggregator_id="aggregator-1",
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator-1",
                role="aggregator",
                base_dir=Path("."),
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1",
                role="client",
                base_dir=Path("."),
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-2",
                role="client",
                base_dir=Path("."),
            ),
        ],
    )
    controller = FLNetInMemoryController(config)
    communicator = FLNetCommunicatorAggregator(
        "http://controller/learning",
        "app-key",
        controller_app_key="aggregator-1",
        client_id="aggregator-1",
        client_ids=["client-1", "client-2"],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=controller.build_session("aggregator-1"),
        timeout=0.5,
        max_polls=5,
    )
    communicator.bind_notice_subject(controller.notice_subject)

    client_1 = FLNetCommunicatorClient(
        "http://controller/learning",
        "app-key",
        controller_app_key="client-1",
        client_id="client-1",
        client_ids=[],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=controller.build_session("client-1"),
    )
    client_2 = FLNetCommunicatorClient(
        "http://controller/learning",
        "app-key",
        controller_app_key="client-2",
        client_id="client-2",
        client_ids=[],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=controller.build_session("client-2"),
    )

    client_1.send_data_to_aggregator(
        np.array([1.0, 2.0]),
        aggregator_name="aggregator-1",
        communication_id="round-1",
    )
    client_2.send_data_to_aggregator(
        np.array([3.0, 4.0]),
        aggregator_name="aggregator-1",
        communication_id="round-1",
    )

    grouped_packages = communicator.await_data_from_clients(
        num_data_packages_per_communication_round=2,
        to_aggregator="aggregator-1",
        communication_id="round-1",
        data_type=np.ndarray,
    )
    packages = grouped_packages["round-1"]
    assert [p.meta.sender for p in packages] == ["client-1", "client-2"]
    assert np.array_equal(packages[0].data, np.array([1.0, 2.0]))
    assert np.array_equal(packages[1].data, np.array([3.0, 4.0]))


def test_await_data_unblocks_when_notice_arrives():
    import threading

    config = FLNetLocalTestConfigDTO(
        aggregator_id="aggregator-1",
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator-1",
                role="aggregator",
                base_dir=Path("."),
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1",
                role="client",
                base_dir=Path("."),
            ),
        ],
    )
    controller = FLNetInMemoryController(config)
    aggregator = FLNetCommunicatorAggregator(
        "http://controller/learning",
        "app-key",
        controller_app_key="aggregator-1",
        client_id="aggregator-1",
        client_ids=["client-1"],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=controller.build_session("aggregator-1"),
        timeout=0.5,
        max_polls=3,
    )
    aggregator.bind_notice_subject(controller.notice_subject)
    client = FLNetCommunicatorClient(
        "http://controller/learning",
        "app-key",
        controller_app_key="client-1",
        client_id="client-1",
        client_ids=[],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=controller.build_session("client-1"),
    )

    result_holder = {}

    def _await():
        result_holder["grouped"] = aggregator.await_data_from_clients(
            num_data_packages_per_communication_round=1,
            communication_id="round-9",
            data_type=np.ndarray,
        )

    thread = threading.Thread(target=_await, daemon=True)
    thread.start()
    client.send_data_to_aggregator(
        np.array([9.0, 10.0]),
        aggregator_name="aggregator-1",
        communication_id="round-9",
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive(), "await_data should unblock after the websocket-style notice"
    packages = result_holder["grouped"]["round-9"]
    assert len(packages) == 1
    assert packages[0].sender == "client-1"
    assert np.array_equal(packages[0].data, np.array([9.0, 10.0]))


def test_local_runner_raises_when_participant_app_missing():
    from pyfedappwrap.engine.federated import (
        FLNetLocalParticipantConfigDTO,
        FLNetLocalTestConfigDTO,
    )
    from pyfedappwrap.engine.tests.federated.runner import LocalFederatedRunner
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "agg").mkdir()
        config = FLNetLocalTestConfigDTO(
            aggregator_id="aggregator",
            participants=[
                FLNetLocalParticipantConfigDTO(
                    participant_id="aggregator",
                    role="aggregator",
                    base_dir=base / "agg",
                ),
            ],
        )
        runner = LocalFederatedRunner(config)
        try:
            runner.run({})
        except KeyError as exc:
            assert "aggregator" in str(exc)
        else:
            raise AssertionError("Expected KeyError when participant app missing")


def test_broadcast_delivers_notice_to_every_client():
    """A broadcast from the aggregator must wake every client's await_data."""
    import threading

    config = FLNetLocalTestConfigDTO(
        aggregator_id="aggregator-1",
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator-1", role="aggregator", base_dir=Path("."),
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1", role="client", base_dir=Path("."),
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-2", role="client", base_dir=Path("."),
            ),
        ],
    )
    controller = FLNetInMemoryController(config)

    aggregator = FLNetCommunicatorAggregator(
        "http://controller/learning",
        "app-key",
        controller_app_key="aggregator-1",
        client_id="aggregator-1",
        client_ids=["client-1", "client-2"],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=controller.build_session("aggregator-1"),
        timeout=1.0,
        max_polls=3,
    )
    aggregator.bind_notice_subject(controller.notice_subject)

    clients = {}
    for cid in ("client-1", "client-2"):
        c = FLNetCommunicatorClient(
            "http://controller/learning",
            "app-key",
            controller_app_key=cid,
            client_id=cid,
            client_ids=[],
            aggregator_id="aggregator-1",
            channel="local-test",
            session=controller.build_session(cid),
            timeout=1.0,
            max_polls=3,
        )
        c.bind_notice_subject(controller.notice_subject)
        clients[cid] = c

    received: dict[str, Any] = {}

    def _await(cid):
        pkg = clients[cid].await_data_from_aggregator(
            aggregator="aggregator-1",
            communication_id="round-broadcast",
            data_type=np.ndarray,
        )
        received[cid] = pkg

    threads = [
        threading.Thread(target=_await, args=(cid,), daemon=True)
        for cid in ("client-1", "client-2")
    ]
    for t in threads:
        t.start()

    aggregator.broadcast(
        "round-broadcast",
        np.array([11.0, 22.0]),
        from_aggregator="aggregator-1"
    )

    for t in threads:
        t.join(timeout=2.0)
        assert not t.is_alive(), "broadcast notice did not wake all clients"

    assert set(received.keys()) == {"client-1", "client-2"}
    for cid, pkg in received.items():
        assert pkg.meta.sender == "aggregator-1"
        assert np.array_equal(pkg.data, np.array([11.0, 22.0]))


def test_stale_notice_is_not_consumed_by_later_filtered_await():
    """A notice from a past round must not satisfy an await filtered on a
    different communication_id. Previously, _consume_matching_notice skipped
    non-matching notices but left them in the pending list forever, where an
    unfiltered subsequent await could mistakenly grab them."""
    config = FLNetLocalTestConfigDTO(
        aggregator_id="aggregator-1",
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator-1", role="aggregator", base_dir=Path("."),
            ),
            FLNetLocalParticipantConfigDTO(
                participant_id="client-1", role="client", base_dir=Path("."),
            ),
        ],
    )
    controller = FLNetInMemoryController(config)
    aggregator = FLNetCommunicatorAggregator(
        "http://controller/learning",
        "app-key",
        controller_app_key="aggregator-1",
        client_id="aggregator-1",
        client_ids=["client-1"],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=controller.build_session("aggregator-1"),
        timeout=0.2,
        max_polls=2,
    )
    aggregator.bind_notice_subject(controller.notice_subject)

    # Inject a stale notice for a round the aggregator never asked about, and
    # do it *without* actually queueing a matching package on the server
    # (simulates a duplicate/leaked notice).
    from pyfedappwrap.engine.service.socket.messages.app import SendFederatedDataNoticeDTO
    from pyfedappwrap.engine.federated.models import FLNetDataNoticeDTO
    from pyfedappwrap.engine.enums.test_embed_states import RunType

    controller.notice_subject.set_state(
        SendFederatedDataNoticeDTO(
            message=FLNetDataNoticeDTO(
                recipient_id="aggregator-1",
                sender_id="client-1",
                communication_id="stale-round",
            ),
            run_type=RunType.FEDERATED_RUN,
        )
    )

    # Awaiting a *different* communication_id must time out instead of being
    # silently "satisfied" by the stale notice.
    try:
        aggregator.await_data_from_clients(
            num_data_packages_per_communication_round=1,
            communication_id="real-round",
            data_type=np.ndarray,
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("Stale notice should not satisfy a mismatched await")


def test_rebinding_notice_subject_releases_previous_observer():
    """Rebinding to a new subject must unregister from the old one so stale
    subjects do not keep live references to the communicator."""
    config = FLNetLocalTestConfigDTO(
        aggregator_id="aggregator-1",
        participants=[
            FLNetLocalParticipantConfigDTO(
                participant_id="aggregator-1", role="aggregator", base_dir=Path("."),
            ),
        ],
    )
    controller_a = FLNetInMemoryController(config)
    controller_b = FLNetInMemoryController(config)
    communicator = FLNetCommunicatorAggregator(
        "http://controller/learning",
        "app-key",
        controller_app_key="aggregator-1",
        client_id="aggregator-1",
        client_ids=[],
        aggregator_id="aggregator-1",
        channel="local-test",
        session=controller_a.build_session("aggregator-1"),
    )

    communicator.bind_notice_subject(controller_a.notice_subject)
    assert len(controller_a.notice_subject.observers) == 1

    communicator.bind_notice_subject(controller_b.notice_subject)
    assert len(controller_a.notice_subject.observers) == 0, \
        "Old subject should have been unsubscribed"
    assert len(controller_b.notice_subject.observers) == 1

    communicator.unbind_notice_subject()
    assert len(controller_b.notice_subject.observers) == 0
    # Idempotent.
    communicator.unbind_notice_subject()
    assert len(controller_b.notice_subject.observers) == 0


def test_local_runner_does_not_leak_observers_across_runs():
    """Calling runner.run() repeatedly must not accumulate observers on the
    shared notice subject."""
    from pyfedappwrap.engine.tests.federated.runner import LocalFederatedRunner
    import tempfile
    system_settings.config_settings_path = "app_federated.yml"

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        agg_dir = base / "agg"
        c1_dir = base / "c1"
        c2_dir = base / "c2"
        for d in (agg_dir, c1_dir, c2_dir):
            (d / "data").mkdir(parents=True, exist_ok=True)
            (d / "output").mkdir(parents=True, exist_ok=True)

        import pandas as pd
        pd.DataFrame([{"x": 1.0, "y": 2.0}]).to_csv(c1_dir / "data" / "input.csv", index=False)
        pd.DataFrame([{"x": 3.0, "y": 4.0}]).to_csv(c2_dir / "data" / "input.csv", index=False)

        config = FLNetLocalTestConfigDTO(
            aggregator_id="aggregator",
            participants=[
                FLNetLocalParticipantConfigDTO(
                    participant_id="aggregator", role="aggregator", base_dir=agg_dir),
                FLNetLocalParticipantConfigDTO(
                    participant_id="client-1", role="client", base_dir=c1_dir,
                    input_file_paths={"input": "input.csv"}),
                FLNetLocalParticipantConfigDTO(
                    participant_id="client-2", role="client", base_dir=c2_dir,
                    input_file_paths={"input": "input.csv"}),
            ],
        )
        from tests.apps.federated_aggregator import MeanVectorAggregator
        runner = LocalFederatedRunner(config, aggregators={"mean": MeanVectorAggregator()})

        from tests.apps.federated_client import FederatedMeanClientApp

        def _fresh_apps():
            return {
                "client-1": FederatedMeanClientApp(),
                "client-2": FederatedMeanClientApp(),
            }

        for _ in range(3):
            results = runner.run(_fresh_apps())
            assert all(r.success for r in results.values()), results
            # After each run observers must be fully released.
            assert len(runner.controller.notice_subject.observers) == 0, (
                f"Observer leak: {len(runner.controller.notice_subject.observers)} "
                f"observers still registered after run"
            )

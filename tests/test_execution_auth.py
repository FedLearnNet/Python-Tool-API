import asyncio
from email.parser import BytesParser
from urllib.parse import parse_qs, urlsplit
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import requests

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import RunType, WebsocketMessageTypes
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service import execution_auth
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.service.socket.socket import WebSocketClient
from pyfedappwrap.engine.service.upload import upload_client


def response(status=200, payload=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload or {"apiKey": "execution-key"}).encode()
    return result


@pytest.mark.parametrize("status", [401, 403, 404, 409])
def test_bootstrap_rejects_unauthorized_missing_and_finished_executions(monkeypatch, status):
    monkeypatch.setattr(execution_auth.requests, "post", lambda *args, **kwargs: response(status))
    with pytest.raises(requests.HTTPError):
        execution_auth.bootstrap_execution("https://backend/api/execution/APP/", 42, "user-token")


def test_bootstrap_requires_user_auth_and_keeps_api_prefix(monkeypatch):
    post = Mock(return_value=response())
    monkeypatch.setattr(execution_auth.requests, "post", post)
    with pytest.raises(ValueError):
        execution_auth.bootstrap_execution("https://backend/api/execution/APP/", 42, None)
    post.assert_not_called()
    assert execution_auth.bootstrap_execution("https://backend/api/execution/workflow/", 42, "user-token") == "execution-key"
    assert post.call_args.args == ("https://backend/api/execution/workflow/42/credential",)
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer user-token"}
    assert post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("http_url,auth_url", [
    ("http://backend/api/testembed/", None),
    ("http://backend/api/execution/APP/", "http://auth/api/testembed/"),
])
@pytest.mark.parametrize("existing_env", [True, False])
def test_local_login_bootstraps_and_saves_an_app_key_once(monkeypatch, tmp_path, http_url, auth_url, existing_env):
    from dotenv import dotenv_values

    env_file = tmp_path / ".env"
    if existing_env:
        env_file.write_text("APP_ID=7\nOTHER_SETTING=preserved\n")
        env_file.chmod(0o644)
    monkeypatch.setitem(system_settings.model_config, "env_file", str(env_file))
    monkeypatch.setattr(system_settings, "app_id", "7")
    monkeypatch.setattr(system_settings, "app_api_key", None)
    monkeypatch.setattr(system_settings, "app_key", None)
    monkeypatch.setattr(system_settings, "dev_mode", True)
    monkeypatch.setattr(system_settings, "http_url", http_url)
    monkeypatch.setattr(system_settings, "auth_url", auth_url)
    monkeypatch.setattr(system_settings, "ws_url", "ws://backend/api/testembed/")
    login = Mock(return_value="oauth-token")
    post = Mock(return_value=response(payload={"apiKey": "app-key"}))
    monkeypatch.setattr(execution_auth.KeycloakClient, "get_token", login)
    monkeypatch.setattr(execution_auth.requests, "post", post)
    set_key = execution_auth.set_key

    def save_key(path, *args):
        # Credentials must never be written while the file is readable by other users.
        assert Path(path).stat().st_mode & 0o777 == 0o600
        return set_key(path, *args)

    monkeypatch.setattr(execution_auth, "set_key", save_key)

    first = execution_auth.authenticate_execution()
    second = execution_auth.authenticate_execution()

    assert first == ("oauth-token", "app-key", http_url, "ws://backend/api/testembed/")
    assert second == (None, "app-key", http_url, "ws://backend/api/testembed/")
    login.assert_called_once()
    post.assert_called_once()
    assert post.call_args.args == (f"{auth_url or http_url}7/credential",)
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer oauth-token"}
    expected = {"APP_ID": "7", "OTHER_SETTING": "preserved"} if existing_env else {}
    assert dotenv_values(env_file) == {**expected, "APP_API_KEY": "app-key"}
    assert env_file.stat().st_mode & 0o777 == 0o600

    root = upload_client.UploadClient(first[0], first[1], base_url=first[2])
    worker = root.for_execution({"id": 100, "executionId": 42, "executionApiKey": "attempt-key"})
    worker.upload_output(RunType.TEST_RUN, 100, {"score": 0.7})
    assert post.call_args.args == ("http://backend/api/execution/APP/42/upload/output",)
    assert post.call_args.kwargs["headers"] == {"X-API-Key": "attempt-key"}


def test_rejected_local_bootstrap_does_not_save_a_key(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setitem(system_settings.model_config, "env_file", str(env_file))
    monkeypatch.setattr(system_settings, "app_api_key", None)
    monkeypatch.setattr(system_settings, "app_key", "oauth-token")
    monkeypatch.setattr(system_settings, "auth_url", "http://auth/api/testembed/")
    monkeypatch.setattr(system_settings, "http_url", "http://backend/testembed/")
    monkeypatch.setattr(execution_auth.requests, "post", Mock(return_value=response(403)))
    with pytest.raises(requests.HTTPError):
        execution_auth.authenticate_execution()
    assert not env_file.exists()


def test_saved_key_skips_auth_url_and_preserves_separate_upload_and_socket_urls(monkeypatch):
    monkeypatch.setattr(system_settings, "app_api_key", "app-key")
    monkeypatch.setattr(system_settings, "app_key", None)
    monkeypatch.setattr(system_settings, "auth_url", "http://auth/api/testembed/")
    monkeypatch.setattr(system_settings, "http_url", "http://uploads/api/execution/APP/")
    monkeypatch.setattr(system_settings, "ws_url", "ws://socket/api/testembed/")
    post = Mock()
    login = Mock()
    monkeypatch.setattr(execution_auth.requests, "post", post)
    monkeypatch.setattr(execution_auth.KeycloakClient, "get_token", login)
    assert execution_auth.authenticate_execution() == (
        None, "app-key", "http://uploads/api/execution/APP/", "ws://socket/api/testembed/")
    post.assert_not_called()
    login.assert_not_called()


def test_explicit_key_takes_precedence_over_oauth(monkeypatch):
    monkeypatch.setattr(system_settings, "http_url", "https://backend/api/execution/tool/")
    monkeypatch.setattr(system_settings, "app_id", "42")
    client = upload_client.UploadClient("user-token", "supplied-key")
    assert client.form_headers == {"X-API-Key": "supplied-key"}
    ws = WebSocketClient("wss://backend/api/execution/tool/42/app", EngineLifecycle(), "user-token", "supplied-key")
    try:
        assert ws.additional_headers == client.form_headers
    finally:
        ws.loop.close()


def test_settings_do_not_print_credentials(monkeypatch):
    monkeypatch.setattr(system_settings, "app_key", "private-user-token")
    monkeypatch.setattr(system_settings, "app_api_key", "private-execution-key")
    assert "private-user-token" not in str(system_settings)
    assert "private-execution-key" not in str(system_settings)


def test_client_configuration_does_not_send_credentials(monkeypatch):
    from pyfedappwrap.engine.events import internal_events

    monkeypatch.setattr(system_settings, "app_key", "private-user-token")
    monkeypatch.setattr(system_settings, "app_api_key", "private-app-key")
    monkeypatch.setattr(internal_events, "load_config", Mock(return_value=None))
    monkeypatch.setattr(internal_events, "list_all_data_files", Mock(return_value=[]))
    send = Mock()
    internal_events.handle_internal_event(BaseSocketMessage(
        type=WebsocketMessageTypes.CLIENT_STARTED, runType=RunType.NOT_DEFINED, message="connected"), send)
    configuration = send.call_args_list[0].args[0].message
    assert "app_key" not in configuration
    assert "app_api_key" not in configuration


@pytest.mark.parametrize("run_type", [RunType.TEST_RUN, RunType.EXPERIMENT_RUN, RunType.FEDERATED_TEST_RUN])
def test_development_upload_uses_attempt_identity_and_credential(monkeypatch, run_type):
    monkeypatch.setattr(system_settings, "http_url", "https://backend/api/testembed/")
    monkeypatch.setattr(system_settings, "app_id", "7")
    post = Mock(return_value=response(201))
    monkeypatch.setattr(upload_client.requests, "post", post)
    client = upload_client.UploadClient("user-token", "engine-key")
    first = client.for_execution({"id": 100, "executionId": 42, "executionApiKey": "attempt-42-key"})
    second = client.for_execution({"id": 101, "executionId": 43, "executionApiKey": "attempt-43-key"})
    first.upload_output(run_type, 100, {"score": 0.7}, meta={"timings": {"RUNTIME": 10}})
    request = post.call_args.kwargs
    assert post.call_args.args == ("https://backend/api/execution/APP/42/upload/output",)
    assert request["data"]["runId"] == "42"
    assert request["headers"] == {"X-API-Key": "attempt-42-key"}
    parts = dict(request["files"])
    assert json.loads(parts["meta"][1]) == {"timings": {"RUNTIME": 10}}
    second.upload_output(run_type, 101, {})
    assert post.call_args.kwargs["headers"] == {"X-API-Key": "attempt-43-key"}
    assert client.api_key == "engine-key"
    with pytest.raises(ValueError, match="another execution"):
        first.upload_output(run_type, 101, {})


def test_regular_upload_rejects_another_execution_and_preserves_batches(monkeypatch):
    monkeypatch.setattr(system_settings, "http_url", "http://backend/execution/APP/")
    monkeypatch.setattr(system_settings, "app_id", "42")
    post = Mock(return_value=response(201))
    monkeypatch.setattr(upload_client.requests, "post", post)
    client = upload_client.UploadClient(None, "supplied-key")
    with pytest.raises(ValueError, match="another execution"):
        client.upload_output(RunType.MODEL_RUN, 43, {})
    post.assert_not_called()
    client.upload_output(RunType.MODEL_RUN, -1, {})
    assert post.call_args.args == ("http://backend/execution/APP/42/upload/output",)
    assert post.call_args.kwargs["data"]["runId"] == "-1"
    assert post.call_args.kwargs["headers"] == {"X-API-Key": "supplied-key"}


@pytest.mark.parametrize("kind", ["model", "output"])
def test_multipart_wire_format(monkeypatch, tmp_path, kind):
    monkeypatch.setattr(system_settings, "http_url", "https://backend/api/execution/APP/")
    monkeypatch.setattr(system_settings, "app_id", "42")
    artifact = tmp_path / "result.txt"
    artifact.write_bytes(b"artifact contents\x00")
    sent = []

    def send(session, request, **kwargs):
        sent.append(request)
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == (5, 120)
        return response(201)

    monkeypatch.setattr(requests.Session, "send", send)
    client = upload_client.UploadClient(None, "attempt-key")
    if kind == "model":
        client.upload_model_file(42, "model", str(artifact))
    else:
        client.upload_output(RunType.TEST_RUN, 42, {"artifact": artifact, "score": 0.7, "empty": None},
                             meta={"timings": {"RUNTIME": 10}})
    request, = sent
    assert request.headers["X-API-Key"] == "attempt-key"
    assert "Authorization" not in request.headers
    assert urlsplit(request.url).path == f"/api/execution/APP/42/upload/{kind}"
    multipart = BytesParser().parsebytes(
        f"Content-Type: {request.headers['Content-Type']}\r\n\r\n".encode() + request.body)
    parts = {part.get_param("name", header="content-disposition"): part for part in multipart.get_payload()}
    assert parts["runId"].get_payload(decode=True) == b"42"
    if kind == "model":
        assert parts["name"].get_payload(decode=True) == b"model"
        assert parts["filePath"].get_payload(decode=True).decode() == str(artifact)
        file = parts["file"]
    else:
        assert parse_qs(urlsplit(request.url).query) == {"runType": [RunType.TEST_RUN.value]}
        assert parts["fields"].get_content_type() == "application/json"
        assert json.loads(parts["fields"].get_payload(decode=True)) == {"score": "0.7"}
        assert json.loads(parts["meta"].get_payload(decode=True)) == {"timings": {"RUNTIME": 10}}
        file = parts["files"]
        assert file["X-Key"] == "artifact"
        assert file["X-Name"] == artifact.name
        assert file.get_content_type() == "text/plain"
    assert file.get_filename() == artifact.name
    assert file.get_payload(decode=True) == artifact.read_bytes()


@pytest.mark.parametrize("status", [302, 401, 403, 409, 500])
@pytest.mark.parametrize("kind", ["model", "output"])
def test_upload_failure_closes_files_and_rejects_redirects(monkeypatch, tmp_path, kind, status):
    monkeypatch.setattr(system_settings, "app_id", "42")
    artifact = tmp_path / "result.bin"
    artifact.write_bytes(b"artifact")
    handles = []

    def post(*args, **kwargs):
        files = kwargs["files"]
        handles.append(files["file"][1] if kind == "model" else files[0][1][1])
        assert not handles[0].closed
        assert kwargs["allow_redirects"] is False
        return response(status)

    monkeypatch.setattr(upload_client.requests, "post", post)
    client = upload_client.UploadClient(None, "attempt-key")
    with pytest.raises(requests.HTTPError):
        if kind == "model":
            client.upload_model_file(42, "model", str(artifact))
        else:
            client.upload_output(RunType.TEST_RUN, 42, {"artifact": artifact})
    assert handles[0].closed


@pytest.mark.parametrize("event_type,run_type", [
    (WebsocketMessageTypes.START_RUN, RunType.TEST_RUN),
    (WebsocketMessageTypes.START_RUN, RunType.EXPERIMENT_RUN),
    (WebsocketMessageTypes.START_PREDICTION, RunType.MODEL_RUN),
])
def test_start_credential_is_owned_by_the_worker_upload_client(monkeypatch, caplog, event_type, run_type):
    from pyfedappwrap.engine.worker import worker_manager

    monkeypatch.setattr(system_settings, "http_url", "http://backend/testembed/")
    manager = worker_manager.WorkerManager(Mock(), upload_client.UploadClient("user-token", "engine-key"),
                                           EngineLifecycle())
    manager.available_worker = Mock()
    worker = Mock()
    monkeypatch.setattr(worker_manager.copy, "deepcopy", Mock(return_value=worker))
    monkeypatch.setattr(worker_manager.threading, "Thread", Mock())
    post = Mock(return_value=response(201))
    monkeypatch.setattr(upload_client.requests, "post", post)
    manager.enqueue_task = Mock()
    event = BaseSocketMessage(
        type=event_type, runType=run_type,
        message={"id": 100, "executionId": 42, "executionApiKey": "secret-attempt-key"},
    )
    manager.update(event)
    _, client, _, worker_run_id, worker_run_type, *_ = worker.set_startup.call_args.args
    assert (worker_run_id, worker_run_type) == (100, run_type)
    client.upload_output(worker_run_type, worker_run_id, {"score": 0.7})
    assert post.call_args.args == ("http://backend/execution/APP/42/upload/output",)
    assert post.call_args.kwargs["data"]["runId"] == "42"
    assert post.call_args.kwargs["headers"] == {"X-API-Key": "secret-attempt-key"}
    assert manager.upload_client.api_key == "engine-key"
    assert event.message == {"id": 100}
    assert manager.enqueue_task.call_args.args[0].body == {"id": 100}
    assert "secret-attempt-key" not in caplog.text


@pytest.mark.parametrize("test_mode", [False, True])
@pytest.mark.parametrize("auth_url", [None, "http://auth/api/execution/APP/"])
def test_runtime_bootstrap_and_standalone_mock_mode(monkeypatch, test_mode, auth_url):
    from pyfedappwrap.engine import runtime

    monkeypatch.setattr(runtime, "RandomTestGeneratorFactory", Mock())
    monkeypatch.setattr(system_settings, "config_settings_path", str(Path(__file__).parent / "configs/data_analysis_app.yml"))

    monkeypatch.setattr(system_settings, "app_api_key", None)
    monkeypatch.setattr(system_settings, "app_key", "user-token")
    monkeypatch.setattr(system_settings, "auth_url", auth_url)
    monkeypatch.setattr(system_settings, "http_url", "http://backend/execution/workflow/")
    monkeypatch.setattr(system_settings, "ws_url", "ws://backend/execution/workflow/")
    monkeypatch.setattr(system_settings, "app_id", "42")
    monkeypatch.setattr(system_settings, "dev_mode", False)
    post = Mock(return_value=response())
    monkeypatch.setattr(execution_auth.requests, "post", post)
    monkeypatch.setattr(execution_auth.KeycloakClient, "get_token", Mock(side_effect=AssertionError("Interactive login")))
    monkeypatch.setattr(runtime, "WebSocketConsoleHandler", lambda _: sys.stdout)
    monkeypatch.setattr(runtime, "print_banner", Mock())
    engine = runtime.FedDBEngine(test_mode=test_mode)
    if test_mode:
        post.assert_not_called()
        assert isinstance(engine.upload_client, runtime.TestUploadClient)
        assert isinstance(engine.ws_client, runtime.TestSocketClient)
    else:
        try:
            assert engine.ws_client.uri == "ws://backend/execution/APP/42/app"
            assert engine.ws_client.additional_headers == {"X-API-Key": "execution-key"}
            assert engine.upload_client.form_headers == engine.ws_client.additional_headers
            post.assert_called_once()
            assert post.call_args.args == (f"{auth_url or 'http://backend/execution/APP/'}42/credential",)
        finally:
            engine.ws_client.loop.close()


def test_production_without_credentials_fails_before_interactive_login(monkeypatch):
    from pyfedappwrap.engine import runtime

    monkeypatch.setattr(runtime, "RandomTestGeneratorFactory", Mock())
    monkeypatch.setattr(system_settings, "config_settings_path", str(Path(__file__).parent / "configs/data_analysis_app.yml"))

    monkeypatch.setattr(system_settings, "app_api_key", " ")
    monkeypatch.setattr(system_settings, "app_key", None)
    monkeypatch.setattr(system_settings, "dev_mode", False)
    get_token = Mock(side_effect=AssertionError("Interactive login"))
    monkeypatch.setattr(execution_auth.KeycloakClient, "get_token", get_token)
    with pytest.raises(ValueError, match="APP_API_KEY"):
        runtime.FedDBEngine(test_mode=False)
    get_token.assert_not_called()


@pytest.mark.parametrize("client_first", [False, True])
@pytest.mark.parametrize("failure", [None, "aggregator", "client", "upload", "missing_aggregator"])
def test_federated_output_is_uploaded_before_terminal_reports(monkeypatch, client_first, failure):
    from pyfedappwrap.engine.worker import federated_worker_manager as federated
    from pyfedappwrap.engine.service.socket.messages.federated import FederatedTestRunCreateDTO

    order = []
    reporter = Mock()
    reporter.update_participant.side_effect = lambda *args, **kwargs: order.append(kwargs.get("status"))
    reporter.finish_run.side_effect = lambda **kwargs: order.append("finish")
    monkeypatch.setattr(federated, "FederatedStatusReporter", Mock(return_value=reporter))
    runner = Mock()
    runner.run.return_value = {
        "aggregator": SimpleNamespace(success=failure != "aggregator", result={"score": 0.7},
                                      error="aggregator failed" if failure == "aggregator" else None),
        "client": SimpleNamespace(success=failure != "client", result={"score": 0.6},
                                  error="client failed" if failure == "client" else None),
    }
    if failure == "missing_aggregator":
        runner.run.return_value.pop("aggregator")
    monkeypatch.setattr(federated, "LocalFederatedRunner", Mock(return_value=runner))
    monkeypatch.setattr(system_settings.fl_test, "use_dockerized_controller", False)
    upload = Mock()
    def upload_output(*args):
        order.append("upload")
        if failure == "upload":
            raise requests.HTTPError("Upload failed")
    upload.upload_output.side_effect = upload_output
    manager = federated.FederatedWorkerManager(Mock(), EngineLifecycle(), upload)
    manager.available_app = SimpleNamespace()
    manager._build_run_config = Mock(return_value=SimpleNamespace(aggregator_id="aggregator", use_external_controller=False))
    participants = [{"participantId": "aggregator", "role": "AGGREGATOR"},
                    {"participantId": "client", "role": "CLIENT"}]
    start = FederatedTestRunCreateDTO(id=100, participants=participants[::-1] if client_first else participants)
    manager._run_federated(start, RunType.FEDERATED_TEST_RUN)
    terminal = [call for call in reporter.update_participant.call_args_list
                if call.kwargs.get("status") in ("FINISHED", "ERROR")]
    if failure == "upload":
        assert terminal == []
        assert reporter.finish_run.call_args.kwargs["status"] == "ERROR"
        assert "Upload failed" in reporter.finish_run.call_args.kwargs["error"]
    else:
        assert {call.args[0] for call in terminal} == set(runner.run.return_value)
        for call in terminal:
            assert call.kwargs["status"] == ("ERROR" if call.args[0] == failure else "FINISHED")
        assert reporter.finish_run.call_args.kwargs["status"] == (
            "ERROR" if failure in ("aggregator", "client") else "FINISHED")
    if failure in ("aggregator", "missing_aggregator"):
        upload.upload_output.assert_not_called()
    else:
        upload.upload_output.assert_called_once()
        assert upload.upload_output.call_args.args[:2] == (RunType.FEDERATED_TEST_RUN, 100)
        if failure != "upload":
            assert order.index("upload") < order.index("FINISHED") < order.index("finish")
            assert upload.upload_output.call_args.args[2] == reporter.finish_run.call_args.kwargs["output_data"]


@pytest.mark.parametrize("token, api_key, headers", [
    ("user-token", None, {"Authorization": "Bearer user-token"}),
    (None, "hosting-key", {"X-API-Key": "hosting-key"}),
])
def test_development_socket_authenticates_once_at_open_and_sends_credential_free_messages(
        monkeypatch, token, api_key, headers):
    from pyfedappwrap.engine.service.socket import socket

    websocket = SimpleNamespace(send=AsyncMock(), close_code=1000)
    connection = AsyncMock()
    connection.__aenter__.return_value = websocket
    connect = Mock(return_value=connection)
    monkeypatch.setattr(socket.websockets, "connect", connect)
    ws = WebSocketClient("ws://backend/testembed/7/app", EngineLifecycle(), token, api_key)

    async def receive_messages():
        ws.send(BaseSocketMessage(type=WebsocketMessageTypes.UPDATE_RUN, runType=RunType.TEST_RUN,
                                  message={"runId": 100, "status": "RUNNING"}))
        ws.send_silent(BaseSocketMessage(type=WebsocketMessageTypes.UPDATE_RUN, runType=RunType.TEST_RUN,
                                         message={"runId": 101, "status": "RUNNING"}))
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    ws.receive_messages = receive_messages
    try:
        ws.loop.run_until_complete(ws.connect())
        connect.assert_called_once_with(ws.uri, additional_headers=headers, open_timeout=30, max_size=None)
        assert websocket.send.await_count == 2
        for call in websocket.send.await_args_list:
            message = json.loads(call.args[0])
            assert set(message) == {"type", "runType", "message"}
            assert token is None or token not in call.args[0]
            assert api_key is None or api_key not in call.args[0]
    finally:
        ws.loop.close()


@pytest.mark.parametrize("state, expected_status", [("expected", 200), ("wrong", 400), ("", 400)])
def test_keycloak_callback_checks_state_without_logging_codes(state, expected_status, caplog):
    from pyfedappwrap.engine.service.keycloak.keycloak import CallbackHandler

    handler = object.__new__(CallbackHandler)
    handler.path = f"/callback?code=secret-auth-code&state={state}"
    handler.server = SimpleNamespace(auth_state="expected", auth_code=None)
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.open_file_response = Mock()
    handler.do_GET()
    handler.send_response.assert_called_once_with(expected_status)
    assert handler.server.auth_code == ("secret-auth-code" if expected_status == 200 else None)
    assert "secret-auth-code" not in caplog.text

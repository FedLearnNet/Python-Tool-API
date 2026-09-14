from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.socket.socket import WebSocketClient
from pyfedappwrap.engine.service.upload.upload_client import UploadClient


def test_websocket_sends_run_api_key_without_oauth():
    client = WebSocketClient(
        "ws://localhost/run/42/app",
        EngineLifecycle(),
        None,
        "run-api-key",
    )
    try:
        assert client.additional_headers == {
            "X-API-Key": "run-api-key",
        }
    finally:
        client.loop.close()


def test_upload_sends_run_api_key_without_oauth():
    client = UploadClient(None, "run-api-key")

    assert client.form_headers == {
        "X-API-Key": "run-api-key",
    }


def test_websocket_still_supports_user_oauth_without_api_key():
    client = WebSocketClient(
        "ws://localhost/run/42/app",
        EngineLifecycle(),
        "oauth-token",
        None,
    )
    try:
        assert client.additional_headers == {
            "Authorization": "Bearer oauth-token",
        }
    finally:
        client.loop.close()

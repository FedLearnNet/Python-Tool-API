import asyncio
from unittest.mock import MagicMock

import pytest

from pyfedappwrap.engine.config.config import ModeType
from pyfedappwrap.engine.enums.test_embed_states import WebsocketMessageTypes
from pyfedappwrap.engine.service.socket.messages.app import AppTaskMessage
from pyfedappwrap.engine.service.socket.socket import WebSocketClient
from pyfedappwrap.learning.base_app import BaseApp


@pytest.mark.parametrize("task,mode", [
    (WebsocketMessageTypes.START_RUN, ()),
    (WebsocketMessageTypes.START_PREDICTION, (ModeType.PREDICTION,)),
])
def test_perform_task_starts_matching_run(task, mode) -> None:
    app = MagicMock()
    app.map.return_value = ("config", "input")
    BaseApp.perform_task(app, AppTaskMessage(task=task, body={}))
    app.start.assert_called_once_with("config", "input", *mode)


def test_unsupported_message_is_ignored() -> None:
    client = WebSocketClient.__new__(WebSocketClient)
    client.lifecycle = MagicMock(is_stopping=MagicMock(side_effect=[False, False, True]))
    client.handle_event = MagicMock()
    client.websocket = MagicMock(recv=MagicMock(side_effect=[
        asyncio.sleep(0, '{"type": "NOT_A_TYPE", "message": null, "runType": "MODEL_RUN"}'),
        asyncio.sleep(0, '{"type": "START_RUN", "message": {"id": 1}, "runType": "MODEL_RUN"}'),
    ]))
    asyncio.run(client.receive_messages())
    client.handle_event.assert_called_once()
    assert client.handle_event.call_args.args[0].type == WebsocketMessageTypes.START_RUN

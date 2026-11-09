from unittest.mock import MagicMock

import pytest
import yaml

from check import TransformationCheckObserver, check_with_timeout, run_with_timeout, save
from pyfedappwrap.engine.enums.test_embed_states import RunType, WebsocketMessageTypes
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.service.socket.messages.transformation import TransformationCheckDTO, \
    TransformationSaveDTO


def _request(body: str, mode: str = "CELL", **kwargs) -> TransformationCheckDTO:
    return TransformationCheckDTO(request_id="r1", body=body, mode=mode, goal={"type": "INT"}, **kwargs)


@pytest.mark.parametrize("request_,success,message", [
    (_request("return int(value) * 2", data={"v": ["1", "2"]}), True, "2 results match"),
    (_request("return value + 'x'", data={"v": ["1"]}), False, "1 of 1 results do not match"),
    (_request("return value * 2", source_goals={"v": {"type": "INT"}}), True, "10 results match"),
    (_request('return {"double": row["a"] * 2}', "ROW", data={"a": [1, 2]}), True, "2 results match"),
    (_request("import os\nreturn 1", data={"v": ["1"]}), False, "importing 'os' is not allowed"),
])
def test_check(request_, success, message) -> None:
    result = check_with_timeout(request_)
    assert (result.request_id, result.is_success) == ("r1", success)
    assert message in result.message


def test_check_times_out() -> None:
    result = check_with_timeout(_request("while True:\n    pass", data={"v": ["1"]}), timeout=2)
    assert not result.is_success
    assert "did not finish within 2 seconds" in result.message


def test_observer_answers_with_result() -> None:
    ws_client = MagicMock()
    TransformationCheckObserver(ws_client).check(BaseSocketMessage(
        type=WebsocketMessageTypes.TRANSFORMATION_CHECK, run_type=RunType.MODEL_RUN,
        message=_request('return {"x": row["a"]}', "ROW", data={"a": [1]}).model_dump(by_alias=True)))
    sent = ws_client.send.call_args.args[0]
    assert sent.type == WebsocketMessageTypes.TRANSFORMATION_CHECK_RESULT
    assert sent.message == {"requestId": "r1", "isSuccess": True, "message": "Test successful, 1 results match the goal",
                            "inputKeys": ["a"], "returnKeys": ["x"], "output": "",
                            "samples": [{"input": {"a": 1}, "output": {"x": 1}, "error": None}]}


def test_check_captures_print_output() -> None:
    result = check_with_timeout(_request('print("seen", value)\nreturn int(value)', data={"v": ["7"]}))
    assert (result.is_success, result.output) == (True, "seen 7\n")


def test_save_generates_a_buildable_project() -> None:
    request = TransformationSaveDTO(name="Double", base_image="ghcr.io/fedlearnnet/python-tool-api/code-transformer-runtimeatest",
                                    **_request("return int(value) * 2", data={"v": ["1"]}).model_dump())
    result = run_with_timeout(save, request)
    assert result.is_success
    assert sorted(result.files) == ["Dockerfile", "app.yml", "code_transformer.py", "main.py", "test.json"]
    assert result.files["Dockerfile"].startswith("FROM ghcr.io/fedlearnnet/python-tool-api/code-transformer-runtimeatest\n")
    app = yaml.safe_load(result.files["app.yml"])
    assert app["info"]["name"] == "Double"
    assert [(c["name"], c["type"]) for c in app["config"]["input"] + app["config"]["output"]] == [
        ("input", "CSV"), ("output", "CSV")]


def test_save_refuses_code_failing_the_check() -> None:
    request = TransformationSaveDTO(name="Broken", base_image="base",
                                    **_request("return value + 'x'", data={"v": ["1"]}).model_dump())
    result = run_with_timeout(save, request)
    assert (result.is_success, result.files) == (False, {})
    assert "do not match" in result.message

import io
import multiprocessing
import tempfile
import threading
from contextlib import redirect_stdout
from pathlib import Path

from pydantic import RootModel, ValidationError
from pydantic_yaml import to_yaml_str

from pyfedappwrap.engine.config.config import AppType, FederatedAppConfigDTO, LocalAppConfig, LocalAppInfo
from pyfedappwrap.engine.enums.test_embed_states import WebsocketMessageTypes
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.service.socket.messages.transformation import TransformationCheckDTO, \
    TransformationCheckResultDTO, TransformationSaveDTO, TransformationSaveResultDTO
from pyfedappwrap.transformation.config.config_writer import DEFAULT_INPUT_CONFIG, DEFAULT_OUTPUT_CONFIG
from pyfedappwrap.transformation.factory.factory_builder import TransformationBuilder
from pyfedappwrap.transformation.factory.factory_test import test_function
from pyfedappwrap.transformation.factory.factory_test_result import TransformationTestCaseDTO

TIMEOUT_SECONDS = 30
_CONTEXT = multiprocessing.get_context("forkserver")
_DOCKERFILE = "FROM {base_image}\nCOPY --chown=nonroot . ./\n"


def check(request: TransformationCheckDTO) -> TransformationCheckResultDTO:
    source_code = TransformationBuilder.wrap_body(request.body, request.mode)
    with redirect_stdout(io.StringIO()) as output:
        result = test_function(request.goal, source_code, request.data, request.source_goals, request.mode)
    return TransformationCheckResultDTO(request_id=request.request_id, output=output.getvalue(), **result.model_dump())


def save(request: TransformationSaveDTO) -> TransformationSaveResultDTO:
    checked = check(request).model_dump(exclude={"output"})
    if not checked["is_success"]:
        return TransformationSaveResultDTO(**checked)
    with tempfile.TemporaryDirectory() as directory:
        builder = TransformationBuilder(TransformationBuilder.wrap_body(request.body, request.mode), request.mode)
        case = TransformationTestCaseDTO.model_validate(request.model_dump(include={"mode", "goal", "source_goals", "data"}))
        builder.register(builder.save(directory), case)
        files = {path.name: path.read_text(encoding="utf-8") for path in Path(directory).iterdir()}
    files["app.yml"] = to_yaml_str(RootModel[LocalAppConfig](LocalAppConfig(
        config=FederatedAppConfigDTO(hyperparams=[], input=[DEFAULT_INPUT_CONFIG], output=[DEFAULT_OUTPUT_CONFIG]),
        info=LocalAppInfo(name=request.name, slug=builder.module_name, type=AppType.DATA_TRANSFORMATION,
                          sourceUrl=None, shortDescription=request.description, longDescription=None))))
    files["Dockerfile"] = _DOCKERFILE.format(base_image=request.base_image)
    return TransformationSaveResultDTO(**checked, files=files)


def run_with_timeout(task, request, timeout: float = TIMEOUT_SECONDS):
    with _CONTEXT.Pool(1) as pool:
        return pool.apply_async(task, (request,)).get(timeout)


def check_with_timeout(request: TransformationCheckDTO,
                       timeout: float = TIMEOUT_SECONDS) -> TransformationCheckResultDTO:
    try:
        return run_with_timeout(check, request, timeout)
    except multiprocessing.TimeoutError:
        return TransformationCheckResultDTO(request_id=request.request_id, is_success=False,
                                            message=f"Check did not finish within {timeout} seconds")


class TransformationCheckObserver:
    def __init__(self, ws_client):
        self.ws_client = ws_client

    def update(self, event: BaseSocketMessage):
        if WebsocketMessageTypes.TRANSFORMATION_CHECK.equals(event.type):
            threading.Thread(target=self.check, args=(event,), daemon=True).start()
        elif WebsocketMessageTypes.TRANSFORMATION_SAVE.equals(event.type):
            threading.Thread(target=self.save, args=(event,), daemon=True).start()

    def check(self, event: BaseSocketMessage):
        try:
            result = check_with_timeout(TransformationCheckDTO.model_validate(event.message))
        except ValidationError as e:
            result = TransformationCheckResultDTO(request_id=str((event.message or {}).get("requestId")),
                                                  is_success=False, message=f"Invalid check request: {e}")
        print(result.output + f"Check {result.request_id}: {result.message}",
              *[f"{s.input!r} -> {s.output!r}: {s.error}" for s in result.samples if s.error], sep="\n")
        self._send(WebsocketMessageTypes.TRANSFORMATION_CHECK_RESULT, result, event)

    def save(self, event: BaseSocketMessage):
        request_id = str((event.message or {}).get("requestId"))
        try:
            result = run_with_timeout(save, TransformationSaveDTO.model_validate(event.message))
        except (ValidationError, multiprocessing.TimeoutError) as e:
            result = TransformationSaveResultDTO(request_id=request_id, is_success=False,
                                                 message=f"Save failed: {e or 'timeout'}")
        print(f"Save {result.request_id}: {result.message}")
        self._send(WebsocketMessageTypes.TRANSFORMATION_SAVE_RESULT, result, event)

    def _send(self, message_type: WebsocketMessageTypes, result, event: BaseSocketMessage):
        self.ws_client.send(BaseSocketMessage(type=message_type, message=result.model_dump(by_alias=True),
                                              run_type=event.run_type))

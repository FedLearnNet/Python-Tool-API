import logging
import threading
from dataclasses import field, dataclass
from typing import Any, Optional

from pyfedappwrap.engine.validate.dto import ToolFileEvaluationResultDTO


@dataclass
class EngineResult:
    success: bool = True
    input_validation: Optional[list[ToolFileEvaluationResultDTO]] = None
    output_validation: Optional[list[ToolFileEvaluationResultDTO]] = None
    error: Exception | str | None = None

    def set_input_validation(self, input_validation: list[ToolFileEvaluationResultDTO]):
        self.input_validation = input_validation
        if not self._check_validation(input_validation):
            self.success = False
            self.error = "Input validation failed:"
        return self

    def set_output_validation(self, output_validation: list[ToolFileEvaluationResultDTO]):
        self.output_validation = output_validation
        if not self._check_validation(output_validation):
            self.success = False
            self.error = "Output validation failed"
        return self

    @staticmethod
    def _check_validation(validation: Optional[list[ToolFileEvaluationResultDTO]]) -> bool:
        if validation is None:
            return True
        for result in validation:
            if not result.ok:
                return False
        return True


@dataclass(slots=True)
class EngineLifecycle:
    stop_event: threading.Event = field(default_factory=threading.Event)
    exit_event: threading.Event = field(default_factory=threading.Event)

    stop_payload: Any = None
    exit_payload: Optional[EngineResult] = None
    test_mode: bool = False

    errors: list[str] = field(default_factory=list)

    def stop(self, payload: Any = None) -> None:
        if payload is not None and self.stop_payload is None:
            self.stop_payload = payload
        self.stop_event.set()

    def request_exit(self, payload: Any = None) -> None:
        if payload is not None and self.exit_payload is None:
            self.exit_payload = EngineResult()
            self.exit_payload.error = payload
            self.exit_payload.success = False
        self.exit_event.set()
        self.stop_event.set()

    def request_exit_output_validation(self, payload: list[ToolFileEvaluationResultDTO]) -> None:
        if self.exit_payload is None:
            self.exit_payload = EngineResult()
        self.exit_payload.set_output_validation(payload)
        self.exit_event.set()

    def request_exit_input_validation(self, payload: list[ToolFileEvaluationResultDTO]) -> None:
        if self.exit_payload is None:
            self.exit_payload = EngineResult()
        self.exit_payload.set_input_validation(payload)
        self.exit_event.set()

    def add_error(self, error: str) -> None:
        self.errors.append(error)

    def is_stopping(self) -> bool:
        return self.stop_event.is_set()

    def stop_event_wait(self, timeout: Optional[float] = None) -> bool:
        return self.stop_event.wait(timeout)

    def is_exiting(self) -> bool:
        return self.exit_event.is_set()

    def request_finish(self) -> None:
        if not self.test_mode:
            logging.info(f"[{self.__class__.__name__}] Stop requested without test mode enabled.")
            return
        self.exit_event.set()
        self.stop_event.set()

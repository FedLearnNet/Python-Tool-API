from enum import Enum
from typing import Any


class TestEmbedEnum(Enum):
    CLIENT_STARTED = "CLIENT_STARTED"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    CONFIG_INITIAL_SEND = "CONFIG_INITIAL_SEND"
    APP_MESSAGE = "APP_MESSAGE"
    LOG_MESSAGE = "LOG_MESSAGE"
    LOG_METRIC = "LOG_METRIC"
    CONSOLE_MESSAGE = "CONSOLE_MESSAGE"
    APP_PERFORMANCE = "APP_PERFORMANCE"

    START_RUN = "START_RUN"
    START_PREDICTION = "START_PREDICTION"
    UPDATE_RUN = "UPDATE_RUN"
    FINISH_RUN = "FINISH_RUN"
    STOP_RUN = "STOP_RUN"

    CONFIG_CLIENT_SEND = "CONFIG_CLIENT_SEND"
    DATA_LIST_CLIENT_SEND = "DATA_LIST_CLIENT_SEND"
    FEDERATED_DATA_NOTICE = "FEDERATED_DATA_NOTICE"

    START_FEDERATED_RUN = "START_FEDERATED_RUN"
    START_FEDERATED_TEST_RUN = "START_FEDERATED_TEST_RUN"
    UPDATE_FEDERATED_RUN = "UPDATE_FEDERATED_RUN"
    FINISH_FEDERATED_RUN = "FINISH_FEDERATED_RUN"
    FEDERATED_PARTICIPANT_UPDATE = "FEDERATED_PARTICIPANT_UPDATE"
    FEDERATED_ROUND_MESSAGE = "FEDERATED_ROUND_MESSAGE"

    SEND_MODEL = "SEND_MODEL"
    SERVER_ERROR = "SERVER_ERROR"
    CLIENT_STOPPED = "CLIENT_STOPPED"



    def equals(self, value: str | Any) -> bool:
        if isinstance(value, Enum):
            return self.value.upper() == value.value.upper()
        if isinstance(value, str):
            return self.value.upper() == value.upper()
        return self.value.upper() == value.upper()


class RunType(Enum):
    TEST_RUN = "TEST_RUN"
    EXPERIMENT_RUN = "EXPERIMENT_RUN"
    PROJECT_RUN = "PROJECT_RUN"
    FEDERATED_RUN = "FEDERATED_RUN"
    FEDERATED_TEST_RUN = "FEDERATED_TEST_RUN"
    MODEL_RUN = "MODEL_RUN"
    NOT_DEFINED = "NOT_DEFINED"

    def equals(self, value: str | Any) -> bool:
        if value is None:
            return False
        if isinstance(value, Enum):
            return self.value.upper() == value.value.upper()
        return self.value.upper() == str(value).upper()

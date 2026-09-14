from contextlib import contextmanager
from threading import local
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict


class FLNetSMPCSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    use_smpc: bool = Field(default=False, alias="useSmpc")
    exponent: int = Field(default=8)
    num_shards: int = Field(default=0, alias="numShards")
    operation: str = Field(default="add")
    enabled: bool = Field(default=False)


class FLNetDPSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    epsilon: float = Field(default=0.99999)
    delta: Optional[float] = Field(default=None)
    sensitivity: Optional[float] = Field(default=None)
    clipping_val: Optional[float] = Field(default=None, alias="clippingVal")
    noise_type: str = Field(default="laplace", alias="noisetype")
    enabled: bool = Field(default=False)

class FLTestSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    use_dockerized_controller: bool = Field(default=False)
    dockerized_controller_orch_url: str = Field(default="http://localhost:8002/")
    dockerized_controller_comm_url: str = Field(default="http://localhost:8003/")
    dockerized_relay_url: str = Field(default="http://localhost:9140/")


class FLRunSettings(BaseModel):
    """Settings for real (non-test) federated runs. Set via environment by the orchestrator that
    starts the app container, e.g. FL_RUN__CONTROLLER_COMM_URL=http://controller:8001."""
    model_config = ConfigDict(populate_by_name=True)

    # Required AppCommunicator endpoint for real federated runs, supplied through
    # FL_RUN__CONTROLLER_COMM_URL. Test runs use their own controller settings.
    controller_comm_url: Optional[str] = Field(default=None)

class KeycloakModel(BaseModel):
    url: str = Field(
        default="https://posymed.featurecloud.ai/auth/realms/FederatedLearningNet_Global")
    client_id: str = Field(default="frontend")
    redirect_uri: str = Field(default="http://localhost:8999/callback")
    server_port: int = Field(default=8999)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter='__',
        env_file='.env',
        env_file_encoding='utf-8',
        protected_namespaces=()
    )

    keycloak: KeycloakModel = KeycloakModel()
    smpc: FLNetSMPCSettings = FLNetSMPCSettings()
    dp: FLNetDPSettings = FLNetDPSettings()
    fl_test: FLTestSettings = FLTestSettings()
    fl_run: FLRunSettings = FLRunSettings()

    app_id: str = Field(default="1")
    app_key: Optional[str] = Field(default=None)
    app_api_key: Optional[str] = Field(default=None)

    enable_config_sync: bool = Field(default=False)
    prio_local_config: bool = Field(default=False)
    trace_performance: bool = Field(default=True)
    enable_project_startup: bool = Field(default=True)
    send_console_log: bool = Field(default=True)
    test_mode: bool = Field(default=False)

    model_dir: str = Field(
        default="./model")  # default also used in app-build-pipeline so be carefull
    data_dir: str = Field(default="./data")

    enable_local_result_saving: bool = Field(default=False)
    enable_remote_result_saving: bool = Field(default=True)

    dev_mode: bool = Field(default=True)

    output_dir: str = Field(default="./")

    config_settings_path: str = Field(default="app.yml")
    read_me_path: str = Field(default="README.md")

    ws_url: str = Field(default="ws://localhost:8080/testembed/")
    http_url: str = Field(default="http://localhost:8080/testembed/")
    url_prefix_remove: str = Field(default="api")

    ws_path: str = Field(default="/app")
    http_upload_path: str = Field(default="upload")

    docker_host_internal: str = Field(default="host.docker.internal")


system_settings = Settings()
_runtime_path_overrides = local()


def get_data_dir() -> str:
    return getattr(_runtime_path_overrides, "data_dir", system_settings.data_dir)


def get_output_dir() -> str:
    return getattr(_runtime_path_overrides, "output_dir", system_settings.output_dir)


@contextmanager
def local_runtime_paths(*, data_dir: Optional[str] = None, output_dir: Optional[str] = None):
    previous_data_dir = getattr(_runtime_path_overrides, "data_dir", None)
    previous_output_dir = getattr(_runtime_path_overrides, "output_dir", None)

    if data_dir is not None:
        _runtime_path_overrides.data_dir = data_dir
    if output_dir is not None:
        _runtime_path_overrides.output_dir = output_dir

    try:
        yield
    finally:
        if previous_data_dir is None:
            if hasattr(_runtime_path_overrides, "data_dir"):
                delattr(_runtime_path_overrides, "data_dir")
        else:
            _runtime_path_overrides.data_dir = previous_data_dir

        if previous_output_dir is None:
            if hasattr(_runtime_path_overrides, "output_dir"):
                delattr(_runtime_path_overrides, "output_dir")
        else:
            _runtime_path_overrides.output_dir = previous_output_dir

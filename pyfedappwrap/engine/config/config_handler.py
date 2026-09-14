import os
from dataclasses import asdict
from typing import Optional

from pydantic import RootModel
from pydantic_yaml import to_yaml_file, parse_yaml_file_as

from pyfedappwrap.engine.config.config import LocalAppConfig, FederatedAppDTO, LocalAppInfo, AppType
from pyfedappwrap.engine.config.system_config import system_settings


def does_config_exist(file_path) -> bool:
    return os.path.exists(file_path)


def load_config(file_path) -> Optional[FederatedAppDTO]:
    try:
        data: RootModel[LocalAppConfig] = parse_yaml_file_as(RootModel[LocalAppConfig], file_path)
        info_data: RootModel[LocalAppInfo] = RootModel[LocalAppInfo](data.root.info)
        info_dict = info_data.model_dump()
        fed_app_dto = FederatedAppDTO(
            **info_dict,
            appConfig=data.root.config
        )
        print(fed_app_dto)
        with open(system_settings.read_me_path, "r", encoding="utf-8") as file:
            fed_app_dto.longDescription = file.read()
        return fed_app_dto
    except Exception as e:
        print(f"Error loading config: {e}")


def load_tool_type(file_path) -> Optional[AppType]:
    config = load_config(file_path)
    if config is not None:
        return config.type
    return None


def _normalized_for_compare(dto: FederatedAppDTO) -> dict:
    d = asdict(dto)
    return d


def is_current_config_equal(file_path: str, new_data: dict) -> bool:
    if not does_config_exist(file_path):
        return False

    current = load_config(file_path)
    if current is None:
        return False

    if _normalized_for_compare(current) != new_data:
        return False
    return True


def save_config(file_path, data: dict):
    try:
        is_current_config_equal(file_path, data)
        # received global model data
        fed_app_dto = RootModel[FederatedAppDTO](data)
        long_description = data.get("longDescription", "")
        fed_app_dto.root.longDescription = None
        app_config = fed_app_dto.root.appConfig
        fed_app_dto.root.appConfig = None
        local_config_dto = LocalAppConfig(
            config=app_config,
            info=fed_app_dto.root
        )
        to_yaml_file(file_path, RootModel[LocalAppConfig](local_config_dto))
        with open(system_settings.read_me_path, "w", encoding="utf-8") as file:
            file.write(long_description)
    except Exception as e:
        print(f"Error saving config: {e}")


def save_config_dto(file_path, data: FederatedAppDTO):
    try:
        # received global model data
        long_description = data.longDescription or ""
        data.longDescription = None
        app_config = data.appConfig
        data.appConfig = None
        local_config_dto = LocalAppConfig(
            config=app_config,
            info=data
        )
        to_yaml_file(file_path, RootModel[LocalAppConfig](local_config_dto))
        with open(system_settings.read_me_path, "w", encoding="utf-8") as file:
            file.write(long_description)
    except Exception as e:
        print(f"Error saving config: {e}")

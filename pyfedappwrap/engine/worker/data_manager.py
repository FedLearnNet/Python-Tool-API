import io
import json
import keyword
import os
import re
from pathlib import Path
from urllib.parse import urlparse
import hashlib
from typing import List, Optional, Any, get_args, get_origin, Union

import pandas as pd

from pyfedappwrap.engine.config.config import FederatedAppInputConfigDTO, \
    ToolConfigDataType
from pyfedappwrap.engine.config.config_handler import load_config
from pyfedappwrap.engine.config.profile import LocalFiles
from pyfedappwrap.engine.config.system_config import get_data_dir, system_settings
from pyfedappwrap.engine.helper.typing_helper import get_dataclass_field_types
from pyfedappwrap.engine.service.upload.helper import download_file, is_remote_resource
from pyfedappwrap.engine.validate.profiler import profile_from_path


def list_all_data_files() -> List[LocalFiles]:
    """
    List all files under a specific directory, returning relative paths.

    Returns:
        List[LocalFiles]: A list of relative file paths found in the directory.
    """
    path = get_data_dir()
    if not os.path.isdir(path):
        os.makedirs(path)
        print(f"The provided path '{path}' did not exist and was created.")

    file_list = []
    for root, _, files in os.walk(path):
        for file in files:
            from_root = str(os.path.join(root, file))
            relative_path = os.path.relpath(from_root, path)
            file_profile = profile_from_path(from_root)
            local_file = LocalFiles.model_validate({
                **file_profile.model_dump(),
                "path": relative_path,
            })
            file_list.append(local_file)

    return file_list


def unwrap_optional(tp: Any) -> Any:
    origin = get_origin(tp)
    args = get_args(tp)

    if origin is Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return tp


def classify_expected_type(tp: Any) -> str | None:
    if tp is None:
        return None

    tp = unwrap_optional(tp)
    origin = get_origin(tp)

    if tp is Path:
        return "path"

    if tp is pd.DataFrame:
        return "dataframe"

    if tp is Any:
        return "dataframe_preferred"

    if tp is dict or origin is dict:
        return "json_dict"

    if tp is list or origin is list:
        return "json_list"

    if tp is str:
        return "text"

    if tp is bytes:
        return "binary"

    if tp in (int, float, bool):
        return "scalar"

    return "unknown"


def get_data(
        input_data_dic: Optional[dict],
        input_file_paths: Optional[dict],
        input_model_type: type | None = None,
        token: Optional[str] = None,
):
    app_configs = load_config(system_settings.config_settings_path)
    if app_configs is None:
        raise ValueError("No app configurations found")

    input_configs = app_configs.appConfig.input
    if input_configs is None:
        raise ValueError("No input configurations found in the app configuration")

    data_dir = get_data_dir()
    data = {}
    input_data_dic = input_data_dic or {}
    input_file_paths = input_file_paths or {}
    expected_types = get_dataclass_field_types(input_model_type) if input_model_type else {}

    for config in input_configs:
        variable_name = sanitize_variable_name(config.name)
        expected_type = expected_types.get(variable_name)

        has_inline_value = variable_name in input_data_dic
        has_file_value = variable_name in input_file_paths

        if not config.required and not has_inline_value and not has_file_value:
            data[variable_name] = None
            continue

        if has_inline_value:
            remote_data = input_data_dic.get(variable_name)
            if remote_data is None and config.required:
                raise ValueError(f"Data not found for variable '{variable_name}'")
            if remote_data is None:
                data[variable_name] = None
                continue

            parsed_data = read_data(
                remote_data,
                config.type,
                config,
                token=token,
                expected_type=expected_type,
            )
            data[variable_name] = parsed_data
            continue

        file_name = input_file_paths.get(variable_name)
        if file_name is None and config.required:
            raise ValueError(f"file_name not set '{variable_name}'")
        if file_name is None:
            data[variable_name] = None
            continue

        file_path = os.path.join(data_dir, file_name)

        if not os.path.exists(file_path):
            expected_kind = classify_expected_type(expected_type)

            if expected_kind == "path":
                data[variable_name] = Path(file_path)
                continue

            if config.required:
                raise FileNotFoundError(f"File '{file_path}' not found")
            data[variable_name] = None
            continue

        parsed_data = read_data(
            str(file_path),
            config.type,
            config,
            token=token,
            expected_type=expected_type,
        )
        data[variable_name] = parsed_data

    return data


def read_inline_dataframe(value) -> Optional[pd.DataFrame]:
    """
    Builds a DataFrame from input that was delivered inline rather than as a path or URL.

    The caller may hand over the rows themselves - a list of row dicts, or the CSV text - which is
    how a batch of rows reaches a transformer app over the websocket. ``pd.read_csv`` treats a bare
    string as a path, so those values have to be recognised before the path/URL handling runs,
    otherwise they fail to parse and fall back to being treated as a file name.

    Returns None when the value is not inline data, so the caller can carry on with its path/URL
    handling.
    """
    if isinstance(value, pd.DataFrame):
        return value

    if isinstance(value, list):
        # A list of row dicts is the natural JSON shape for a batch of rows.
        return pd.DataFrame(value)

    if isinstance(value, str) and not is_remote_resource(value):
        # Multi-line text is the CSV itself; a single line is far more likely to be a file name.
        if "\n" in value.strip():
            return pd.read_csv(io.StringIO(value))

    return None


def try_read_dataframe(
        file_path,
        data_type: ToolConfigDataType,
        config: FederatedAppInputConfigDTO,
        token: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    try:
        inline = read_inline_dataframe(file_path)
        if inline is not None:
            return inline

        match data_type:
            case ToolConfigDataType.CSV:
                return get_csv(
                    file_path,
                    token,
                    sep=config.delimiter or ",",
                    index_col=config.indexCol,
                    has_header=True if config.hasHeader is None else config.hasHeader,
                )

            case ToolConfigDataType.TSV:
                return get_csv(
                    file_path,
                    token,
                    sep="\t",
                    index_col=config.indexCol,
                    has_header=True if config.hasHeader is None else config.hasHeader,
                )

            case ToolConfigDataType.JSON:
                return get_json(file_path, token, as_dataframe=True)

            case _:
                return None
    except Exception:
        return None


def try_read_json_structure(
        file_path,
        data_type: ToolConfigDataType,
        token: Optional[str] = None,
) -> Optional[dict | list]:
    try:
        match data_type:
            case ToolConfigDataType.JSON:
                parsed = get_json(file_path, token, as_dataframe=False)
                if isinstance(parsed, (dict, list)):
                    return parsed
                return None

            case ToolConfigDataType.TEXT | ToolConfigDataType.STRING | ToolConfigDataType.UNKNOWN:
                raw = get_string(file_path, token)
                parsed = json.loads(raw)
                if isinstance(parsed, (dict, list)):
                    return parsed
                return None

            case _:
                return None
    except Exception:
        return None


def cast_scalar(value: Any, expected_type: Any) -> Any:
    expected_type = unwrap_optional(expected_type)

    if expected_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            val = value.strip().lower()
            if val in {"true", "1", "yes", "y"}:
                return True
            if val in {"false", "0", "no", "n"}:
                return False
            raise ValueError(f"Cannot cast '{value}' to bool")
        return bool(value)

    return expected_type(value)


def read_data(
        file_path,
        data_type: str | ToolConfigDataType,
        config: FederatedAppInputConfigDTO,
        token: Optional[str] = None,
        expected_type: Any = None,
):
    """
    Reads and parses the data from the given file path based on the specified data type
    and optionally the expected Python target type from the input dataclass.

    Mapping priority:
    - Path -> return Path
    - pd.DataFrame -> try DataFrame, fallback Path
    - Any -> try DataFrame, fallback Path
    - dict/list -> prefer JSON structure
    - str -> text/string
    - bytes -> binary
    - int/float/bool -> scalar cast
    - else -> use config.type fallback behavior
    """
    try:
        if isinstance(data_type, str):
            try:
                data_type = ToolConfigDataType(data_type.upper())
            except ValueError as e:
                raise ValueError(f"Unsupported data type: {data_type}") from e
        elif not isinstance(data_type, ToolConfigDataType):
            raise ValueError(f"Unsupported data type: {data_type}")

        expected_kind = classify_expected_type(expected_type)

        # Minimal override based on expected field type
        if expected_kind == "path":
            return get_path(file_path, token)

        if expected_kind in {"dataframe", "dataframe_preferred"}:
            df = try_read_dataframe(file_path, data_type, config, token)
            if df is not None:
                return df
            return get_path(file_path, token)

        if expected_kind == "json_dict":
            parsed = try_read_json_structure(file_path, data_type, token)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError(f"Expected dict-like input for '{file_path}'")

        if expected_kind == "json_list":
            parsed = try_read_json_structure(file_path, data_type, token)
            if isinstance(parsed, list):
                return parsed
            raise ValueError(f"Expected list-like input for '{file_path}'")

        if expected_kind == "text":
            match data_type:
                case ToolConfigDataType.HTML:
                    return get_html(file_path, token)
                case ToolConfigDataType.TEXT | ToolConfigDataType.STRING | ToolConfigDataType.UNKNOWN:
                    return get_string(file_path, token)
                case ToolConfigDataType.JSON:
                    parsed = get_json(file_path, token, as_dataframe=False)
                    return json.dumps(parsed, ensure_ascii=False)
                case _:
                    return get_string(file_path, token)

        if expected_kind == "binary":
            return get_image(file_path, token)

        if expected_kind == "scalar":
            match data_type:
                case ToolConfigDataType.JSON:
                    parsed = get_json(file_path, token, as_dataframe=False)
                    if isinstance(parsed, (dict, list)):
                        raise ValueError(f"Cannot cast structured JSON to scalar '{expected_type}'")
                    return cast_scalar(parsed, expected_type)
                case _:
                    raw = get_string(file_path, token).strip()
                    return cast_scalar(raw, expected_type)

        # Original fallback behavior
        match data_type:
            case ToolConfigDataType.CSV:
                return get_csv(
                    file_path,
                    token,
                    sep=config.delimiter or ",",
                    index_col=config.indexCol,
                    has_header=True if config.hasHeader is None else config.hasHeader
                )

            case ToolConfigDataType.TSV:
                return get_csv(
                    file_path,
                    token,
                    sep="\t",
                    index_col=config.indexCol,
                    has_header=True if config.hasHeader is None else config.hasHeader
                )

            case ToolConfigDataType.JSON:
                return get_json(file_path, token)

            case ToolConfigDataType.HTML:
                return get_html(file_path, token)

            case ToolConfigDataType.IMAGE:
                return get_image(file_path, token)

            case ToolConfigDataType.TEXT:
                return get_text(file_path, token)

            case ToolConfigDataType.STRING:
                return get_string(file_path, token)

            case ToolConfigDataType.PATH:
                return get_path(file_path, token)

            case ToolConfigDataType.UNKNOWN:
                return get_unknown(file_path, token)

            case _:
                raise ValueError(f"Unsupported data type: {data_type}")

    except Exception as e:
        raise ValueError(
            f"Error parsing data '{file_path}' with type '{data_type}'"
            f"{'' if expected_type is None else f' and expected type {expected_type}'}: {e}"
        ) from e


# Copy from Java part
def sanitize_variable_name(name):
    # Convert camelCase or PascalCase to snake_case
    snake_case = re.sub(r'([a-z])([A-Z]+)', r'\1_\2', name).lower()
    # Replace invalid characters with underscores
    sanitized = re.sub(r'[^0-9a-zA-Z_]', '_', snake_case)
    # Variable names must not start with a digit
    if sanitized and sanitized[0].isdigit():
        sanitized = '_' + sanitized
    # Ensure the name is not a Python keyword
    if keyword.iskeyword(sanitized):
        sanitized += '_var'
    return sanitized


def get_csv(file, token, *, sep=",", has_header: bool = True, index_col: Optional[int] = None):
    if is_remote_resource(file):
        response = download_file(file, token, as_utf_8=True)
        if response is not None:
            return pd.read_csv(
                io.StringIO(response),
                sep=sep,
                index_col=index_col,
                header=0 if has_header else None,
                low_memory=False,
            )
    return pd.read_csv(
        file,
        sep=sep,
        header=0 if has_header else None,
        index_col=index_col,
        low_memory=False,
    )


def get_json(
        file: str | Path,
        token: Optional[str] = None,
        *,
        as_dataframe: bool = True,
        orient: Optional[str] = None,
        **kwargs,
) -> pd.DataFrame | dict | list:
    if is_remote_resource(file):
        content = _download_text(str(file), token)
        if as_dataframe:
            return pd.read_json(io.StringIO(content), orient=orient, **kwargs)
        return json.loads(content)

    if as_dataframe:
        return pd.read_json(file, orient=orient, **kwargs)

    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)


def get_string(file: str | Path, token: Optional[str] = None, *, encoding: str = "utf-8") -> str:
    if is_remote_resource(file):
        return _download_text(str(file), token)
    return Path(file).read_text(encoding=encoding)


def get_text(file: str | Path, token: Optional[str] = None, *, encoding: str = "utf-8") -> str:
    return get_string(file, token, encoding=encoding)


def get_html(file: str | Path, token: Optional[str] = None, *, encoding: str = "utf-8") -> str:
    return get_string(file, token, encoding=encoding)


def get_unknown(file: str | Path, token: Optional[str] = None, *, encoding: str = "utf-8") -> str:
    return get_string(file, token, encoding=encoding)


def get_path(file: str | Path, token: Optional[str] = None) -> Path:
    if is_remote_resource(file):
        return _download_to_local_path(str(file), token)
    return Path(file)


def get_image(file: str | Path, token: Optional[str] = None) -> bytes:
    if is_remote_resource(file):
        return _download_bytes(str(file), token)
    return Path(file).read_bytes()


def _download_text(file: str, token: Optional[str] = None) -> str:
    response = download_file(file, token, as_utf_8=True)
    if response is None:
        raise ValueError(f"Could not download remote text resource '{file}'")
    if not isinstance(response, str):
        raise ValueError(f"Expected text response for '{file}', got {type(response).__name__}")
    return response


def _download_bytes(file: str, token: Optional[str] = None) -> bytes:
    response = download_file(file, token, as_utf_8=False)
    if response is None:
        raise ValueError(f"Could not download remote binary resource '{file}'")
    if isinstance(response, bytes):
        return response
    if isinstance(response, str):
        return response.encode("utf-8")
    raise ValueError(f"Expected bytes response for '{file}', got {type(response).__name__}")


def _download_to_local_path(file: str, token: Optional[str] = None) -> Path:
    response = download_file(file, token, as_utf_8=False)
    if response is None:
        raise ValueError(f"Could not download remote resource '{file}'")

    download_dir = Path(get_data_dir()) / ".download_cache"
    download_dir.mkdir(parents=True, exist_ok=True)

    parsed = urlparse(file)
    original_name = Path(parsed.path).name or "downloaded_resource"
    safe_name = re.sub(r"[^0-9a-zA-Z._-]", "_", original_name)
    unique_prefix = hashlib.sha256(file.encode("utf-8")).hexdigest()[:16]
    local_path = download_dir / f"{unique_prefix}_{safe_name}"

    if isinstance(response, bytes):
        local_path.write_bytes(response)
        return local_path

    if isinstance(response, str):
        local_path.write_text(response, encoding="utf-8")
        return local_path

    raise ValueError(f"Unsupported download response type for '{file}': {type(response).__name__}")

from __future__ import annotations

from typing import Optional, List

from pyfedappwrap.engine.config.config import (
    FederatedAppDTO,
    FederatedAppInputConfigDTO,
    FederatedAppOutputConfigDTO,
    TabularSchemaDTO, FederatedAppBaseConfigDTO, ToolConfigDataType,
)
from pyfedappwrap.engine.config.config_handler import load_config, save_config_dto
from pyfedappwrap.types.transformation.base_transformer import BaseTransformerAPP
from pyfedappwrap.types.transformation.function_analyzer import (
    TransformFunctionAnalyzer,
    ParameterInfo,
)

DEFAULT_INPUT_CONFIG = FederatedAppInputConfigDTO(
    name="input",
    type=ToolConfigDataType.CSV,
    description="Input for the transformation, autogen",
)

DEFAULT_OUTPUT_CONFIG = FederatedAppOutputConfigDTO(
    name="output",
    type=ToolConfigDataType.CSV,
    description="Output for the transformation, autogen",
)


def write_transformer_config(file_path: str, app: BaseTransformerAPP) -> None:
    """
    Generates config for a transformer by:
      - deriving input/output tabular schema from the first transform parameter
      - keeping remaining parameters as classic hyperparams
    """
    config: Optional[FederatedAppDTO] = load_config(file_path)
    if config is None:
        raise RuntimeError("Failed to load existing configuration.")

    analyzer = TransformFunctionAnalyzer(app.transform)
    analysis_result = analyzer.analyze()

    params: List[ParameterInfo] = [p for p in analysis_result["parameters"] if p.name != "self"]

    config.appConfig.input = [DEFAULT_INPUT_CONFIG]
    config.appConfig.output = [DEFAULT_OUTPUT_CONFIG]

    if not params:
        save_config_dto(file_path, config)
        return

    first_param = params[0]

    if analysis_result.get("is_on_row", False):
        in_cols = list(first_param.keys or [])
        out_cols = analysis_result.get("return_keys", [])

        _set_tabular_schema(
            config.appConfig.input[0],
            columns=in_cols,
            description=_schema_doc("Input row schema", first_param),
        )
        _set_tabular_schema(
            config.appConfig.output[0],
            columns=out_cols,
            description=_schema_doc("Output row schema", first_param),
        )
    else:
        col_name = "column"
        _set_tabular_schema(
            config.appConfig.input[0],
            columns=[col_name],
            description=_schema_doc("Input column schema", first_param),
        )
        _set_tabular_schema(
            config.appConfig.output[0],
            columns=[col_name],
            description=_schema_doc("Output column schema", first_param),
        )

    save_config_dto(file_path, config)


def _set_tabular_schema(
        io_cfg: FederatedAppBaseConfigDTO,
        *,
        columns: List[str],
        description: str,
) -> None:
    """
    Writes a minimal TabularSchemaDTO into the given IO config.
    Adjust TabularColumnDTO field names if your DTO differs.
    """
    if not columns:
        io_cfg.tabularSchema = None
        return

    io_cfg.description = description
    io_cfg.hasHeader = True
    io_cfg.delimiter = ","

    io_cfg.tabularSchema = TabularSchemaDTO(
        requiredColumns=columns
    )


def _schema_doc(prefix: str, param: ParameterInfo) -> str:
    if param.doc:
        return f"{prefix}. {param.doc}"
    return f"{prefix} (derived from '{param.name}'), autogen"

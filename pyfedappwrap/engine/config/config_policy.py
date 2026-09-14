from typing import Dict

from pydantic.dataclasses import dataclass

from pyfedappwrap.engine.config.config import AppType


@dataclass(frozen=True)
class ToolTypeNeedsConfig:
    needs_input_config: bool
    can_edit_input_config: bool
    needs_output_config: bool
    can_edit_output_config: bool

    # training / prediction
    supports_training: bool

    # data transformation
    can_edit_only_schema: bool

    @staticmethod
    def defaults() -> "ToolTypeNeedsConfig":
        return ToolTypeNeedsConfig(
            needs_input_config=True,
            can_edit_input_config=True,
            needs_output_config=True,
            can_edit_output_config=True,
            supports_training=False,
            can_edit_only_schema=False,
        )

TOOL_TYPE_CONFIG_DEFAULT_OPTIONS: ToolTypeNeedsConfig = ToolTypeNeedsConfig.defaults()

# This class defines the configuration policy for different tool types in the federated learning application.
# It specifies whether a tool type needs input/output configuration, whether it supports training, and other related settings.
#
# Frontend: projects/global-app/src/app/modules/tool-development/model/tool-config-type.ts
# Backend: global-learning-api/src/main/java/de/unihamburg/daibetes/api/app/config/ToolTypeConfigPolicy.java
# Python: pyfedappwrap/engine/config/config-policy.py
TOOL_TYPE_CONFIG_MAP: Dict[AppType, ToolTypeNeedsConfig] = {
    AppType.PRE_PROCESSING: ToolTypeNeedsConfig(
        needs_input_config=True,
        can_edit_input_config=True,
        needs_output_config=True,
        can_edit_output_config=True,
        supports_training=False,
        can_edit_only_schema=False,
    ),
    AppType.ANALYSIS: ToolTypeNeedsConfig(
        needs_input_config=True,
        can_edit_input_config=True,
        needs_output_config=True,
        can_edit_output_config=True,
        supports_training=True,
        can_edit_only_schema=False,
    ),
    AppType.SELF_LEARNED: ToolTypeNeedsConfig(
        needs_input_config=True,
        can_edit_input_config=True,
        needs_output_config=True,
        can_edit_output_config=True,
        supports_training=False,
        can_edit_only_schema=False,
    ),
    AppType.DATA_TRANSFORMATION: ToolTypeNeedsConfig(
        needs_input_config=True,
        can_edit_input_config=False,
        needs_output_config=True,
        can_edit_output_config=False,
        supports_training=False,
        can_edit_only_schema=True,
    ),
    AppType.EXTRACTOR: ToolTypeNeedsConfig(
        needs_input_config=False,
        can_edit_input_config=False,
        needs_output_config=True,
        can_edit_output_config=False,
        supports_training=False,
        can_edit_only_schema=False,
    ),
    AppType.POST_PROCESSING: ToolTypeNeedsConfig(
        needs_input_config=True,
        can_edit_input_config=True,
        needs_output_config=True,
        can_edit_output_config=True,
        supports_training=False,
        can_edit_only_schema=False,
    ),
    AppType.EVALUATION: ToolTypeNeedsConfig(
        needs_input_config=True,
        can_edit_input_config=True,
        needs_output_config=True,
        can_edit_output_config=True,
        supports_training=False,
        can_edit_only_schema=False,
    ),
    AppType.EXPORT: ToolTypeNeedsConfig(
        needs_input_config=False,
        can_edit_input_config=False,
        needs_output_config=True,
        can_edit_output_config=True,
        supports_training=False,
        can_edit_only_schema=False,
    ),
}

def get_tool_type_config(
    tool_type: AppType | None,
) -> ToolTypeNeedsConfig:
    if tool_type is None:
        return TOOL_TYPE_CONFIG_DEFAULT_OPTIONS
    return TOOL_TYPE_CONFIG_MAP.get(
        tool_type, TOOL_TYPE_CONFIG_DEFAULT_OPTIONS
    )
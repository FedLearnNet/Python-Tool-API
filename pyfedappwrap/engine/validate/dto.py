from typing import Any, List, Dict, Optional

from pydantic import BaseModel, Field


class ToolFileEvaluationResultDTO(BaseModel):
    ok: bool
    name: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def success(name: Optional[str]):
        return ToolFileEvaluationResultDTO(
            ok=True,
            name=name,
            errors=[],
            meta={},
        )

    @staticmethod
    def warn(msg: str, name: Optional[str]):
        return ToolFileEvaluationResultDTO(
            ok=True,
            name=name,
            errors=[msg],
            meta={},
        )

    @staticmethod
    def fail(msg: str, name: Optional[str]):
        return ToolFileEvaluationResultDTO(
            ok=False,
            name=name,
            errors=[msg],
            meta={},
        )

    @staticmethod
    def str(result: 'ToolFileEvaluationResultDTO'):
        status = "OK" if result.ok else "FAIL"
        name_display = f'"{result.name}"' if result.name else "N/A"

        if result.errors:
            errors_display = "\n    ".join(result.errors)
            errors_section = f"\n  Errors:\n    {errors_display}"
        else:
            errors_section = "\n  Errors: None"

        return (
            f"ToolFileEvaluationResult:\n"
            f"  Name: {name_display}\n"
            f"  Status: {status}"
            f"{errors_section}"
        )

    @staticmethod
    def str_list(result: list['ToolFileEvaluationResultDTO']):
        separator = "\n" + "=" * 60 + "\n"
        return separator.join([ToolFileEvaluationResultDTO.str(r) for r in result])

import inspect
import logging
import types
from pathlib import Path
from typing import Any, Optional, Union, get_type_hints

from pydantic import TypeAdapter, ValidationError
from pydantic.alias_generators import to_snake

from pyfedappwrap.transformation.base_transformer import BaseTransformerAPP
from pyfedappwrap.transformation.config.transformer_config import BaseTransformerConfig
from pyfedappwrap.transformation.transformation_mode import FunctionExecutionMode

_MODE_INPUT = {
    FunctionExecutionMode.ROW: ({}, "a dict"),
    FunctionExecutionMode.PATIENT: ([], "a list of row dicts"),
    FunctionExecutionMode.CELL: ("1", "a single value"),
}


class TransformationBuilder:
    """
    Builds a transformation from source code and saves it to disk.

    The source code must define exactly one concrete subclass of ``BaseTransformerAPP``. It is
    loaded once when the builder is created, so an invalid source fails right away.

    With a ``mode``, ``transform`` must also take what that mode passes it: ROW a dict,
    PATIENT a list of row dicts, CELL a single value. A missing type hint is not checked.

    WARNING: loading executes arbitrary code in the current process, only use it inside the
    sandboxed tool container.

    Raises:
        ValueError: If the source code is empty, does not compile, fails to execute, does not
            define exactly one transformation class or its ``transform`` does not fit ``mode``.
    """

    def __init__(self, source_code: str, mode: Optional[FunctionExecutionMode] = None):
        if not isinstance(source_code, str) or not source_code.strip():
            raise ValueError("Source code must not be empty")
        self.source_code = source_code
        self.mode = mode
        self.transformer_class = self._load_transformer_class()
        self.module_name = to_snake(self.transformer_class.__name__)

    def build(self, config: Optional[BaseTransformerConfig] = None) -> BaseTransformerAPP:
        cls = self.transformer_class
        transformer = cls.__new__(cls)
        transformer.config = config if config is not None else BaseTransformerConfig()
        transformer.logger = logging.getLogger(cls.__name__)
        return transformer

    def save(self, directory: Union[str, Path], overwrite: bool = False) -> Path:
        path = Path(directory) / f"{self.module_name}.py"
        if path.exists() and not overwrite:
            raise FileExistsError(f"Transformation {path} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        # written next to the target and moved into place, so the file is never half written
        tmp = path.with_suffix(".py.tmp")
        tmp.write_text(self.source_code, encoding="utf-8")
        return tmp.replace(path)

    def register(self, path: Path) -> None:
        """Registers the saved transformation in main.py for a later build. Not implemented yet."""

    def _load_transformer_class(self) -> type[BaseTransformerAPP]:
        module = types.ModuleType("pyfedappwrap_transformation_source")
        try:
            exec(compile(self.source_code, "<transformation>", "exec"),
                 module.__dict__)  # pylint: disable=exec-used
        except SyntaxError as e:
            raise ValueError(f"Source code does not compile, line {e.lineno}: {e.msg}") from e
        except Exception as e:  # pylint: disable=broad-exception-caught
            raise ValueError(f"Executing the source code failed, {type(e).__name__}: {e}") from e

        candidates = [obj for obj in vars(module).values()
                      if inspect.isclass(obj)
                      and issubclass(obj, BaseTransformerAPP)
                      and obj.__module__ == module.__name__
                      and not inspect.isabstract(obj)]
        if len(candidates) != 1:
            names = ", ".join(c.__name__ for c in candidates) or "none"
            raise ValueError("Source code must define exactly one subclass of BaseTransformerAPP "
                             f"implementing transform, found: {names}")
        self._check_transform(candidates[0])
        return candidates[0]

    def _check_transform(self, cls: type[BaseTransformerAPP]) -> None:
        transform = cls.transform
        if inspect.iscoroutinefunction(transform) or inspect.isgeneratorfunction(transform):
            raise ValueError(f"{cls.__name__}.transform must return its result, "
                             "not be async or a generator")

        signature = inspect.signature(transform)
        try:
            signature.bind(None, None)
        except TypeError as e:
            raise ValueError(f"{cls.__name__}.transform{signature} must take exactly one "
                             f"argument, {e}") from None

        param = list(signature.parameters.values())[1]
        if self.mode is None or param.kind is param.VAR_POSITIONAL:
            return
        sample, expected = _MODE_INPUT[self.mode]
        try:
            annotation = get_type_hints(transform).get(param.name, Any)
            TypeAdapter(annotation).validate_python(sample)
        except ValidationError:
            raise ValueError(f"{cls.__name__}.transform takes {param.name}: "
                             f"{getattr(annotation, '__name__', annotation)}, but a "
                             f"{self.mode.value} transformation passes {expected}") from None
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # type hints pydantic cannot resolve or handle are not checked

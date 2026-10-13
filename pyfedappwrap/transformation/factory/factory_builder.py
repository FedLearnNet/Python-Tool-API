import ast
import importlib.util
import inspect
import logging
import textwrap
import types
from pathlib import Path
from typing import Any, Optional, Union, get_type_hints

from pydantic import TypeAdapter, ValidationError
from pydantic.alias_generators import to_snake

from pyfedappwrap.transformation.base_transformer import BaseTransformerAPP
from pyfedappwrap.transformation.config.function_analyzer import TransformFunctionAnalyzer
from pyfedappwrap.transformation.config.transformer_config import BaseTransformerConfig
from pyfedappwrap.transformation.factory.factory_test_result import TransformationTestCaseDTO
from pyfedappwrap.transformation.transformation_mode import FunctionExecutionMode

_MODE_INPUT = {
    FunctionExecutionMode.ROW: ({}, "a dict"),
    FunctionExecutionMode.PATIENT: ([], "a list of row dicts"),
    FunctionExecutionMode.CELL: ("1", "a single value"),
}
_HEADERS = {
    FunctionExecutionMode.ROW: "def transform(self, row: dict):",
    FunctionExecutionMode.PATIENT: "def transform(self, rows: list[dict]):",
    FunctionExecutionMode.CELL: "def transform(self, value):",
}
_TEMPLATE = ("from pyfedappwrap.transformation.base_transformer import BaseTransformerAPP, BaseTransformerConfig\n"
             "class CodeTransformer(BaseTransformerAPP[BaseTransformerConfig]):\n"
             "    {header}\n"
             "{body}\n")
_MAIN = ("from pyfedappwrap.transformation.factory.factory_main import run\n"
         "from {module} import {cls}\n\n"
         "if __name__ == \"__main__\":\n"
         "    run({cls})\n")
TEST_FILE = "test.json"
_BLOCKED_MODULES = {"os", "sys", "subprocess", "socket", "shutil", "importlib", "ctypes"}
_BLOCKED_NAMES = {"exec", "eval", "open", "compile", "__import__"}


class TransformationBuilder:
    """
    Builds a transformation from source code and saves it to disk.

    The source code must define exactly one concrete subclass of ``BaseTransformerAPP``. It is
    loaded once when the builder is created, so an invalid source fails right away.

    With a ``mode``, ``transform`` must also take what that mode passes it: ROW a dict,
    PATIENT a list of row dicts, CELL a single value. A missing type hint is not checked.

    Before executing, the source is checked statically: only installed libraries outside a
    blocked list may be imported, and blocked builtins and dunder attributes are rejected.

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
        tree = self._check_source()
        self.transformer_class = self._load_transformer_class(tree)
        self.module_name = to_snake(self.transformer_class.__name__)
        self.input_keys, self.return_keys = self._keys(tree)

    @staticmethod
    def wrap_body(body: str, mode: FunctionExecutionMode) -> str:
        """The source of a transformation whose ``transform`` has ``body``, its code starts at line 4."""
        return _TEMPLATE.format(header=_HEADERS[mode], body=textwrap.indent(textwrap.dedent(body), " " * 8))

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
        return self._write(path, self.source_code)

    def register(self, path: Path, case: TransformationTestCaseDTO) -> Path:
        """Writes main.py serving the saved transformation, in test mode it is tested against ``case``."""
        self._write(path.parent / TEST_FILE, case.model_dump_json(by_alias=True))
        return self._write(path.parent / "main.py",
                           _MAIN.format(module=path.stem, cls=self.transformer_class.__name__))

    @staticmethod
    def _write(path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        # written next to the target and moved into place, so the file is never half written
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        return tmp.replace(path)

    def _check_source(self) -> ast.Module:
        try:
            tree = ast.parse(self.source_code)
        except SyntaxError as e:
            raise ValueError(f"Source code does not compile, line {e.lineno}: {e.msg}") from e
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for module in [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]:
                    root = module.split(".")[0]
                    if not root or root in _BLOCKED_MODULES:
                        raise ValueError(f"Line {node.lineno}: importing '{module}' is not allowed")
                    if importlib.util.find_spec(root) is None:
                        raise ValueError(f"Line {node.lineno}: '{module}' is not installed, "
                                         "only installed libraries can be used")
            name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
            if name in _BLOCKED_NAMES or isinstance(node, ast.Attribute) and name.startswith("__"):
                raise ValueError(f"Line {node.lineno}: using '{name}' is not allowed")
        return tree

    def _load_transformer_class(self, tree: ast.Module) -> type[BaseTransformerAPP]:
        module = types.ModuleType("pyfedappwrap_transformation_source")
        try:
            exec(compile(tree, "<transformation>", "exec"), module.__dict__)  # pylint: disable=exec-used
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

    @staticmethod
    def _keys(tree: ast.Module) -> tuple[list[str], list[str]]:
        transform = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "transform")
        analyzer = TransformFunctionAnalyzer(None)
        param = transform.args.args[1].arg if len(transform.args.args) > 1 else ""
        return list(dict.fromkeys(analyzer.extract_keys(transform, param))), analyzer.extract_return_keys(transform)

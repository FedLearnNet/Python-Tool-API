import ast
import inspect
import re
import textwrap
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, get_type_hints


@dataclass
class ParameterInfo:
    """Container for function parameter metadata."""
    name: str
    keys: List[str]
    default_value: Any
    type: str
    choices: List[Any]
    doc: str


class TransformFunctionAnalyzer(ast.NodeVisitor):
    """
    Analyzer specifically designed for inspecting the `transform` method
    inside subclasses of BaseTransformerAPP.
    It extracts parameter metadata, key accesses, and dictionary return keys.
    """

    def __init__(self, method):
        self.method = method
        self.parameters: List[ParameterInfo] = []
        self.return_keys: List[str] = []
        self.doc: str = ""

    def analyze(self):
        """
        Parses and analyzes the given `transform` function source code.
        """
        src = inspect.getsource(self.method)
        src = textwrap.dedent(src)
        tree = ast.parse(src)
        self.visit(tree)
        return {
            "parameters": self.parameters,
            "return_keys": self.return_keys,
            "doc": self.doc,
            "is_on_row": self.check_on_row(),
        }

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.parameters = self.get_parameters_info(node)
        self.return_keys = self.extract_return_keys(node)
        self.doc = ast.get_docstring(node) or ""
        self.generic_visit(node)

    @staticmethod
    def extract_param_docs(docstring: str, parameter_name: str) -> str:
        pattern = rf'^.*{parameter_name}.*:.*$'
        matches = re.findall(pattern, docstring, re.MULTILINE)
        cleaned_lines = [
            re.sub(rf'.*{parameter_name}.*?:\s*', '', match)
            for match in matches
        ]
        return "\n".join(cleaned_lines)

    def get_parameters_info(self, node: ast.FunctionDef) -> List[ParameterInfo]:
        parameters = []
        type_hints = get_type_hints(self.method)
        default_values = {arg.arg: None for arg in node.args.args}

        if node.args.defaults:
            for arg, default in zip(reversed(node.args.args), reversed(node.args.defaults)):
                default_values[arg.arg] = self.get_default_value(default)

        for arg in node.args.args:
            param_name = arg.arg
            param_type = type_hints.get(param_name, None)
            param_keys = self.extract_keys(node, param_name)
            choices = {}
            if isinstance(param_type, type) and issubclass(param_type, Enum):
                choices = {e.name: e.value for e in param_type}

            default_value = default_values.get(param_name)
            param_doc = self.extract_param_docs(ast.get_docstring(node) or "", param_name)

            parameters.append(ParameterInfo(
                name=param_name,
                keys=param_keys,
                default_value=default_value,
                type=param_type.__name__ if param_type else 'string',
                choices=[v for _, v in choices.items()],
                doc=param_doc
            ))
        return parameters

    def get_default_value(self, node, choices=None):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [self.get_default_value(e) for e in node.elts]
        if isinstance(node, ast.Dict):
            return {self.get_default_value(k): self.get_default_value(v) for k, v in
                    zip(node.keys, node.values)}
        if isinstance(node, ast.Tuple):
            return tuple(self.get_default_value(e) for e in node.elts)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            if choices and node.attr in choices:
                return choices[node.attr]
            return f"{node.value.id}.{node.attr}"
        return None

    def extract_keys(self, node: ast.AST, param_name: str) -> List[str]:
        keys = []
        for child in ast.walk(node):
            if (isinstance(child, ast.Subscript)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == param_name):
                if hasattr(child.slice, 'value'):
                    if isinstance(child.slice.value, str):
                        keys.append(child.slice.value)
                elif isinstance(child.slice, ast.Constant):
                    keys.append(child.slice.value)

        return keys

    def extract_return_keys(self, node: ast.FunctionDef) -> List[str]:
        keys = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Return):
                if isinstance(child.value, ast.Dict):
                    for key in child.value.keys:
                        if isinstance(key, ast.Str):
                            keys.add(key.s)
                        elif isinstance(key, ast.Constant):
                            keys.add(key.value)
        return list(keys)

    def check_on_row(self) -> bool:
        """
        Determines if the function processes per-row transformations,
        inferred from key access patterns or dictionary returns.
        """
        if any(len(p.keys) > 0 for p in self.parameters):
            return True
        if len(self.return_keys) > 0:
            return True
        return False

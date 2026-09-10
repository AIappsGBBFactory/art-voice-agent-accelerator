"""Restricted Jinja preview with synchronous, deterministic work and output limits.

Only JSON enters the sandbox. An AST allowlist precedes compilation; injected
guards meter every expression and every loop iteration (including empty-output
loops). No timeout thread, template loader, external callable, or runtime client
is involved. This is deliberately separate from normal agent rendering.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from apps.artagent.backend.api.v1.schemas.prompt_preview import (
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    MAX_OUTPUT_BYTES,
    MAX_PROMPT_BYTES,
    PromptPreviewError,
    check_json_budget,
)
from jinja2 import TemplateSyntaxError, Undefined, UndefinedError, meta, nodes
from jinja2.runtime import LoopContext
from jinja2.sandbox import SandboxedEnvironment, SecurityError
from jinja2.utils import pass_context
from jinja2.visitor import NodeTransformer

MAX_TEMPLATE_NODES = 4096
MAX_TEMPLATE_DEPTH = 48
MAX_TEMPLATE_TOKENS = 16_000
MAX_LOOP_ITERATIONS = 1000
MAX_RENDER_WORK = 80_000
MAX_MISSING_PATHS = 128
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_METHODS = {"get", "items", "keys", "values", "split", "format"}
_DICT_METHODS = set(dir(dict))
_LOOP_ATTRIBUTES = {"index", "index0", "revindex", "revindex0", "first", "last", "length"}
_FILTERS = {
    "default",
    "d",
    "lower",
    "upper",
    "title",
    "capitalize",
    "trim",
    "length",
    "join",
    "replace",
    "tojson",
    "string",
    "int",
    "float",
    "round",
    "first",
    "last",
    "list",
}
_TESTS = {
    "defined",
    "undefined",
    "none",
    "boolean",
    "true",
    "false",
    "string",
    "number",
    "mapping",
    "sequence",
    "iterable",
    "integer",
    "float",
    "even",
    "odd",
    "eq",
    "equalto",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "in",
}
_ALLOWED_NODES = {
    nodes.Template,
    nodes.Output,
    nodes.TemplateData,
    nodes.Name,
    nodes.Const,
    nodes.Getattr,
    nodes.Getitem,
    nodes.Slice,
    nodes.List,
    nodes.Tuple,
    nodes.Dict,
    nodes.Pair,
    nodes.Keyword,
    nodes.Filter,
    nodes.Test,
    nodes.If,
    nodes.For,
    nodes.Assign,
    nodes.Call,
    nodes.CondExpr,
    nodes.Compare,
    nodes.Operand,
    nodes.And,
    nodes.Or,
    nodes.Not,
    nodes.Neg,
    nodes.Pos,
    nodes.Add,
    nodes.Sub,
    nodes.Mul,
    nodes.Div,
    nodes.FloorDiv,
    nodes.Mod,
}


def template_path(parent: str, key: str | int) -> str:
    """Use bracket notation for dictionary keys that collide with Python attributes."""
    if isinstance(key, int):
        return f"{parent}[{key}]"
    if _IDENTIFIER.fullmatch(key) and key not in _DICT_METHODS:
        return f"{parent}.{key}" if parent else key
    return f"{parent}[{json.dumps(key, ensure_ascii=False)}]"


class PreviewLimitError(ValueError):
    """A deterministic size, nesting, output, or work limit was reached."""


@dataclass
class SandboxResult:
    """A preview is successful only when no diagnostics were produced."""

    rendered: str | None = None
    errors: list[PromptPreviewError] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    references: set[str] = field(default_factory=set)


@dataclass
class _Budget:
    work: int = 0
    iterations: int = 0
    line: int | None = None
    missing_paths: dict[str, int | None] = field(default_factory=dict)
    object_paths: dict[int, str] = field(default_factory=dict)

    def charge(self, amount: int = 1) -> None:
        self.work += amount
        if self.work > MAX_RENDER_WORK:
            raise PreviewLimitError("Template work limit exceeded.")

    def check_value(self, value: Any) -> None:
        pending = [(value, 0)]
        size = 0
        count = 0
        while pending:
            item, depth = pending.pop()
            self.charge()
            count += 1
            if depth > MAX_JSON_DEPTH or count > MAX_JSON_NODES:
                raise PreviewLimitError("Template value structure limit exceeded.")
            if isinstance(item, Undefined):
                continue
            if isinstance(item, str):
                self.charge(len(item) // 128)
                size += len(item.encode("utf-8")) * 2 + 2
            elif type(item) in (list, tuple, dict):
                if len(item) > MAX_JSON_NODES:
                    raise PreviewLimitError("Template collection limit exceeded.")
                size += len(item) * 4 + 2
                if type(item) is dict:
                    pending.extend((part, depth + 1) for pair in item.items() for part in pair)
                else:
                    pending.extend((part, depth + 1) for part in item)
            elif item is None or type(item) is bool:
                size += 5
            elif type(item) in (int, float):
                if abs(item) > 10**100 or not math.isfinite(item):
                    raise PreviewLimitError("Template numeric limit exceeded.")
                size += 104
            else:
                raise SecurityError("Only JSON values may be rendered.")
            if size > MAX_OUTPUT_BYTES * 2:
                raise PreviewLimitError("Template value size limit exceeded.")

    def checked_expression(self, value: Any, line: int) -> Any:
        self.line = line
        self.charge()
        if isinstance(value, (LoopContext, Undefined, slice)) or _json_method(value):
            return value
        self.check_value(value)
        return value

    def iterate(self, value: Any, line: int):
        self.line = line
        self.charge()
        if not isinstance(value, (list, tuple, dict, str, Undefined)):
            raise SecurityError("Only bounded JSON collections may be iterated.")
        for item in value:
            self.line = line
            self.iterations += 1
            self.charge()
            if self.iterations > MAX_LOOP_ITERATIONS:
                raise PreviewLimitError("Template loop limit exceeded.")
            yield item


def _json_method(value: Any) -> bool:
    """Recognize only bound built-in methods; never inspect an input Python object."""
    if type(value) is not type({}.get):
        return False
    owner = value.__self__
    return (type(owner) is dict and value.__name__ in {"get", "items", "keys", "values"}) or (
        type(owner) is str and value.__name__ in {"split", "format"}
    )


def _undefined_type(budget: _Budget) -> type[Undefined]:
    class PreviewUndefined(Undefined):
        """Keep Jinja's false conditions/defaults, but diagnose missing output."""

        def _record(self) -> None:
            parent = budget.object_paths.get(id(self._undefined_obj), "")
            name = self._undefined_name
            path = template_path(parent, name) if parent else str(name or "undefined")
            if path not in budget.missing_paths and len(budget.missing_paths) >= MAX_MISSING_PATHS:
                raise PreviewLimitError("Too many unavailable template paths.")
            budget.missing_paths.setdefault(path, budget.line)

        def __str__(self) -> str:
            self._record()
            return ""

        def __iter__(self):
            self._record()
            return iter(())

        def __len__(self) -> int:
            self._record()
            return 0

        def _fail_with_undefined_error(self, *args: Any, **kwargs: Any) -> Any:
            self._record()
            raise UndefinedError("A required template variable is unavailable.")

        __getitem__ = _fail_with_undefined_error

    return PreviewUndefined


class _GuardExpressions(NodeTransformer):
    def generic_visit(self, node: nodes.Node, *args: Any, **kwargs: Any) -> nodes.Node:
        node = super().generic_visit(node, *args, **kwargs)
        if isinstance(node, nodes.For):
            node.iter = nodes.Call(
                nodes.Name("_preview_iter", "load"),
                [node.iter, nodes.Const(node.lineno)],
                [],
                None,
                None,
            ).set_lineno(node.lineno)
        # Jinja emits Slice as Python subscription syntax, not as a value.
        if (
            isinstance(node, nodes.Expr)
            and not isinstance(node, nodes.Slice)
            and getattr(node, "ctx", "load") == "load"
        ):
            return nodes.Call(
                nodes.Name("_preview_expr", "load"),
                [node, nodes.Const(node.lineno)],
                [],
                None,
                None,
            ).set_lineno(node.lineno)
        return node


def _private_key(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("_")


class _PreviewEnvironment(SandboxedEnvironment):
    intercepted_binops = frozenset({"+", "-", "*", "/", "//", "%", "**"})
    intercepted_unops = frozenset({"+", "-"})

    def __init__(self, budget: _Budget) -> None:
        super().__init__(undefined=_undefined_type(budget), autoescape=False, optimized=False)
        self.budget = budget
        self.globals.clear()
        self.globals.update(
            _preview_expr=budget.checked_expression,
            _preview_iter=budget.iterate,
        )
        original_filters = self.filters
        self.filters = {name: self._filter(name, original_filters[name]) for name in _FILTERS}
        self.tests = {name: self.tests[name] for name in _TESTS}
        self.finalize = self._string

    def _string(self, value: Any) -> str:
        self.budget.check_value(value)
        text = str(value)
        if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise PreviewLimitError("Template output limit exceeded.")
        return text

    def getattr(self, obj: Any, attribute: str) -> Any:
        self.budget.charge()
        if _private_key(attribute):
            raise SecurityError("Private attributes are not available.")
        if type(obj) is dict:
            if attribute in {"get", "items", "keys", "values"}:
                return getattr(obj, attribute)
            if attribute in _DICT_METHODS:
                raise SecurityError("Dictionary methods are restricted.")
            if attribute in obj:
                return obj[attribute]
        elif type(obj) is str and attribute in {"split", "format"}:
            return getattr(obj, attribute)
        elif isinstance(obj, LoopContext) and attribute in _LOOP_ATTRIBUTES:
            return getattr(obj, attribute)
        elif isinstance(obj, Undefined):
            return obj._fail_with_undefined_error()
        return self.undefined(obj=obj, name=attribute)

    def getitem(self, obj: Any, argument: Any) -> Any:
        self.budget.charge()
        if type(argument) not in (str, int, slice):
            raise SecurityError("A lookup requires a string key or integer index.")
        if isinstance(argument, str) and len(argument) > 128:
            raise PreviewLimitError("Lookup key size limit exceeded.")
        if _private_key(argument):
            raise SecurityError("Private dictionary keys are not available.")
        if isinstance(obj, Undefined):
            return obj._fail_with_undefined_error()
        if type(obj) is dict and type(argument) in (str, int):
            # Unlike the default sandbox, never fall back from keys to methods.
            return obj.get(argument, self.undefined(obj=obj, name=argument))
        if type(obj) in (list, tuple, str) and isinstance(argument, (int, slice)):
            try:
                return obj[argument]
            except (IndexError, TypeError):
                pass
        return self.undefined(obj=obj, name=argument)

    def call(self, context: Any, obj: Any, *args: Any, **kwargs: Any) -> Any:
        self.budget.charge()
        # Jinja adds these compiler-owned scopes to calls made inside loops.
        kwargs.pop("_loop_vars", None)
        kwargs.pop("_block_vars", None)
        if obj == self.globals["_preview_expr"] or obj == self.globals["_preview_iter"]:
            return obj(*args, **kwargs)
        if not _json_method(obj):
            raise SecurityError("Only safe JSON lookups and string formatting may be called.")
        owner, method = obj.__self__, obj.__name__
        self.budget.check_value([list(args), kwargs])
        if type(owner) is dict:
            if kwargs:
                raise SecurityError("Dictionary lookup keywords are not supported.")
            if method == "get":
                if not 1 <= len(args) <= 2 or type(args[0]) not in (str, int):
                    raise SecurityError("Dictionary get requires a JSON key.")
                if _private_key(args[0]):
                    raise SecurityError("Private dictionary keys are not available.")
                if isinstance(args[0], str) and len(args[0]) > 128:
                    raise PreviewLimitError("Lookup key size limit exceeded.")
                return owner.get(*args)
            if args:
                raise SecurityError("Dictionary iteration takes no arguments.")
            return list(obj())
        if method == "format":
            if owner not in {"{:,}", "{:,.2f}"} or len(args) != 1 or kwargs:
                raise SecurityError("Only bounded numeric display formats are supported.")
            if type(args[0]) not in (int, float):
                raise SecurityError("Numeric formatting requires a number.")
        elif method == "split":
            if len(args) > 2 or set(kwargs) - {"sep", "maxsplit"}:
                raise SecurityError("Unsupported split arguments.")
        result = obj(*args, **kwargs)
        self.budget.check_value(result)
        return result

    def call_binop(self, context: Any, operator: str, left: Any, right: Any) -> Any:
        self.budget.charge()
        if isinstance(left, Undefined) or isinstance(right, Undefined):
            value = left if isinstance(left, Undefined) else right
            return value._fail_with_undefined_error()
        if operator == "**" or type(left) not in (int, float) or type(right) not in (int, float):
            raise SecurityError("Only bounded numeric arithmetic is supported.")
        result = self.binop_table[operator](left, right)
        self.budget.check_value(result)
        return result

    def call_unop(self, context: Any, operator: str, arg: Any) -> Any:
        if type(arg) not in (int, float):
            raise SecurityError("Only numeric unary operators are supported.")
        return self.unop_table[operator](arg)

    def _filter(self, name: str, original: Any) -> Any:
        @pass_context
        def bounded(context: Any, value: Any, *args: Any, **kwargs: Any) -> Any:
            self.budget.charge()
            self.budget.check_value([value, list(args), kwargs])
            if name == "join":
                if kwargs.keys() - {"d"} or len(args) > 1:
                    raise SecurityError("Join supports a separator, not attribute lookup.")
                separator = self._string(args[0] if args else kwargs.get("d", ""))
                parts: list[str] = []
                size = 0
                for item in self.budget.iterate(value, self.budget.line or 1):
                    text = self._string(item)
                    size += len(text.encode("utf-8")) + (
                        len(separator.encode("utf-8")) if parts else 0
                    )
                    if size > MAX_OUTPUT_BYTES:
                        raise PreviewLimitError("Join output limit exceeded.")
                    parts.append(text)
                return separator.join(parts)
            if name == "replace":
                if len(args) < 2:
                    raise SecurityError("Replace requires an old and a new string.")
                text, old, new = self._string(value), self._string(args[0]), self._string(args[1])
                if (
                    len(text.encode("utf-8")) + text.count(old) * len(new.encode("utf-8"))
                    > MAX_OUTPUT_BYTES
                ):
                    raise PreviewLimitError("Replace output limit exceeded.")
            if name == "tojson" and (args or kwargs):
                indent = args[0] if args else kwargs.get("indent")
                if indent is not None and (type(indent) is not int or not 0 <= indent <= 8):
                    raise PreviewLimitError("JSON indentation limit exceeded.")
            if name == "round":
                precision = args[0] if args else kwargs.get("precision", 0)
                if type(precision) is not int or not -100 <= precision <= 100:
                    raise PreviewLimitError("Numeric precision limit exceeded.")
            pass_arg = getattr(original, "jinja_pass_arg", None)
            if pass_arg is not None:
                argument = {
                    "environment": self,
                    "eval_context": context.eval_ctx,
                    "context": context,
                }[pass_arg.name]
                result = original(argument, value, *args, **kwargs)
            else:
                result = original(value, *args, **kwargs)
            self.budget.check_value(result)
            return result

        return bounded


def _parse_and_validate(environment: _PreviewEnvironment, prompt: str) -> nodes.Template:
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise PreviewLimitError("Prompt size limit exceeded.")
    nesting = 0
    for count, (line, token, value) in enumerate(environment.lex(prompt), 1):
        environment.budget.line = line
        if count > MAX_TEMPLATE_TOKENS:
            raise PreviewLimitError("Template token limit exceeded.")
        if token == "operator":
            if value in {"(", "[", "{"}:
                nesting += 1
            elif value in {")", "]", "}"}:
                nesting -= 1
            if nesting > MAX_TEMPLATE_DEPTH:
                raise PreviewLimitError("Template nesting limit exceeded.")
    parsed = environment.parse(prompt)
    pending = [(parsed, 0)]
    count = 0
    while pending:
        node, depth = pending.pop()
        environment.budget.line = node.lineno
        count += 1
        if count > MAX_TEMPLATE_NODES or depth > MAX_TEMPLATE_DEPTH:
            raise PreviewLimitError("Template structure limit exceeded.")
        if type(node) not in _ALLOWED_NODES:
            raise SecurityError("This template operation is not supported in preview.")
        if isinstance(node, nodes.Name) and _private_key(node.name):
            raise SecurityError("Private names are not available.")
        if isinstance(node, nodes.Keyword) and _private_key(node.key):
            raise SecurityError("Private keyword arguments are not available.")
        if isinstance(node, nodes.Getattr) and _private_key(node.attr):
            raise SecurityError("Private attributes are not available.")
        if (
            isinstance(node, nodes.Getitem)
            and isinstance(node.arg, nodes.Const)
            and _private_key(node.arg.value)
        ):
            raise SecurityError("Private dictionary keys are not available.")
        if isinstance(node, nodes.For) and node.recursive:
            raise SecurityError("Recursive loops are not supported.")
        if isinstance(node, nodes.Assign) and not isinstance(node.target, nodes.Name):
            raise SecurityError("Only local variable assignments are supported.")
        if isinstance(node, nodes.Filter) and node.name not in _FILTERS:
            raise SecurityError("This filter is not supported in preview.")
        if isinstance(node, nodes.Test) and node.name not in _TESTS:
            raise SecurityError("This test is not supported in preview.")
        if isinstance(node, nodes.Call):
            if (
                not isinstance(node.node, nodes.Getattr)
                or node.node.attr not in _METHODS
                or node.dyn_args is not None
                or node.dyn_kwargs is not None
            ):
                raise SecurityError("Only safe dictionary and string methods may be called.")
            if node.node.attr == "format" and not (
                isinstance(node.node.node, nodes.Const)
                and node.node.node.value in {"{:,}", "{:,.2f}"}
            ):
                raise SecurityError("Only bounded numeric display formats are supported.")
        pending.extend((child, depth + 1) for child in node.iter_child_nodes())
    return parsed


def render_prompt_preview(prompt: str, context: dict[str, Any]) -> SandboxResult:
    """Render sanitized JSON, returning explicit diagnostics instead of raw source."""
    result = SandboxResult()
    budget = _Budget()
    environment = _PreviewEnvironment(budget)
    try:
        check_json_budget(context)
        pending = [(value, key) for key, value in context.items()]
        while pending:
            value, path = pending.pop()
            if type(value) in (dict, list):
                budget.object_paths.setdefault(id(value), path)
                items = value.items() if type(value) is dict else enumerate(value)
                pending.extend((child, template_path(path, key)) for key, child in items)
        parsed = _parse_and_validate(environment, prompt)
        result.references = meta.find_undeclared_variables(parsed)
        guarded = _GuardExpressions().visit(parsed)
        template = environment.from_string(guarded)
        parts: list[str] = []
        size = 0
        for part in template.generate(**context):
            size += len(part.encode("utf-8"))
            if size > MAX_OUTPUT_BYTES:
                raise PreviewLimitError("Template output limit exceeded.")
            parts.append(part)
        if not budget.missing_paths:
            result.rendered = "".join(parts)
    except TemplateSyntaxError as exc:
        result.errors.append(
            PromptPreviewError(message="Invalid Jinja syntax.", line=exc.lineno, kind="syntax")
        )
    except SecurityError:
        result.errors.append(
            PromptPreviewError(
                message="Unsafe or unsupported template operation.", line=budget.line, kind="unsafe"
            )
        )
    except (PreviewLimitError, RecursionError):
        result.errors.append(
            PromptPreviewError(
                message="Preview size, nesting, output, or work limit exceeded.",
                line=budget.line,
                kind="limit",
            )
        )
    except UndefinedError:
        if not budget.missing_paths:
            result.errors.append(
                PromptPreviewError(
                    message="A required template variable is unavailable.",
                    line=budget.line,
                    kind="undefined",
                )
            )
    except (ValueError, TypeError, ArithmeticError, KeyError, OverflowError):
        result.errors.append(
            PromptPreviewError(
                message="Template values cannot be used in this expression.",
                line=budget.line,
                kind="render",
            )
        )
    result.missing = sorted(budget.missing_paths)
    result.errors.extend(
        PromptPreviewError(
            message="A required template variable is unavailable.", line=line, kind="undefined"
        )
        for line in budget.missing_paths.values()
    )
    return result

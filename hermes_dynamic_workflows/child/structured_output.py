"""Structured output for workflow child agents."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import contextvars
import threading
from typing import Any, Callable, Iterable, Iterator

_CURRENT_CHILD_TASK_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_CURRENT_CHILD_TASK_ID", default=""
)

from ..core.schema import validate_json_schema, validate_schema
from ..core.tool_errors import tool_error

STRUCTURED_OUTPUT_TOOL_NAME = "structured_output"
STRUCTURED_OUTPUT_TOOLSET = "workflow_structured"
STRUCTURED_OUTPUT_SUCCESS = "Structured output provided successfully"
STRUCTURED_OUTPUT_CONTINUE_MESSAGE = (
    "ERROR: You provided text instead of calling the structured_output tool. "
    "Do NOT send text, markdown, or prose summaries. Call the structured_output tool function NOW "
    "with your structured JSON payload to complete this request."
)
MAX_STRUCTURED_OUTPUT_RETRIES = 5

# The registered schema is only a process-global placeholder. Each workflow
# child gets an instance-local copy whose parameters are replaced with the
# schema passed to agent(..., {schema}).
STRUCTURED_OUTPUT_TOOL_SCHEMA = {
    "description": "Return structured output in the requested format",
    "parameters": {
        "type": "object",
        "additionalProperties": True,
        "properties": {},
    },
}


def build_tool_schema_instruction() -> str:
    return (
        f"\n\nUse the {STRUCTURED_OUTPUT_TOOL_NAME} tool to return your final response "
        "in the requested structured format. You MUST call this tool exactly once "
        "at the end of your response to provide the structured output."
    )


def _sanitize_tool_parameters_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Sanitize JSON Schema for LLM tool function parameters (strip $schema, replace const with enum)."""
    def _clean_node(node: Any) -> Any:
        if isinstance(node, dict):
            res = {}
            for k, v in node.items():
                if k in ("$schema", "$id", "$comment"):
                    continue
                if k == "const":
                    res["enum"] = [v]
                    if "type" not in res and "type" not in node:
                        if isinstance(v, str):
                            res["type"] = "string"
                        elif isinstance(v, bool):
                            res["type"] = "boolean"
                        elif isinstance(v, int):
                            res["type"] = "integer"
                else:
                    res[k] = _clean_node(v)
            return res
        elif isinstance(node, list):
            return [_clean_node(item) for item in node]
        return node

    return _clean_node(deepcopy(schema))


def specialize_structured_output_tool(
    tools: list[dict[str, Any]] | None,
    schema: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return child-local tool definitions with the target schema installed."""
    validate_json_schema(schema)
    sanitized_schema = _sanitize_tool_parameters_schema(schema)
    specialized = list(tools or [])
    for index, definition in enumerate(specialized):
        function = definition.get("function") if isinstance(definition, dict) else None
        if not isinstance(function, dict) or function.get("name") != STRUCTURED_OUTPUT_TOOL_NAME:
            continue
        replacement = deepcopy(definition)
        replacement_function = replacement["function"]
        replacement_function["description"] = "Return structured output in the requested format"
        replacement_function["parameters"] = sanitized_schema
        specialized[index] = replacement
        return specialized
    raise RuntimeError("structured_output tool is not available to the workflow child")


class _StructuredOutputBroker:
    """Thread-safe per-child store of expected schemas and accepted results."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._expect: dict[str, dict[str, Any]] = {}
        self._results: dict[str, Any] = {}
        self._attempts: dict[str, int] = {}
        self._last_errors: dict[str, str] = {}
        self._on_exhausted: dict[str, Callable[[], Any]] = {}
        self._exhausted: set[str] = set()

    def register(
        self,
        task_id: str,
        schema: dict[str, Any],
        on_exhausted: Callable[[], Any] | None = None,
    ) -> None:
        if not task_id:
            return
        with self._lock:
            self._expect[task_id] = schema
            self._attempts[task_id] = 0
            self._results.pop(task_id, None)
            self._last_errors.pop(task_id, None)
            self._exhausted.discard(task_id)
            if on_exhausted is None:
                self._on_exhausted.pop(task_id, None)
            else:
                self._on_exhausted[task_id] = on_exhausted

    def submit(self, task_id: str, value: Any) -> tuple[bool, str]:
        target = str(task_id or "").strip() or _CURRENT_CHILD_TASK_ID.get("")
        if not target:
            return False, "root: missing structured-output task identity"
        with self._lock:
            schema = self._expect.get(target)
            if schema is None:
                return False, (
                    "root: no structured-output expectation is registered for task "
                    f"{target!r}"
                )
            attempts = self._attempts.get(target, 0) + 1
            self._attempts[target] = attempts
        if attempts > MAX_STRUCTURED_OUTPUT_RETRIES:
            error = (
                "root: maximum structured output attempts exceeded "
                f"({MAX_STRUCTURED_OUTPUT_RETRIES})"
            )
            with self._lock:
                self._last_errors[target] = error
            return False, error

        errors = _validation_errors(value, schema)
        if errors:
            error = ", ".join(errors)
            with self._lock:
                self._last_errors[target] = error
            if attempts >= MAX_STRUCTURED_OUTPUT_RETRIES:
                self._interrupt_exhausted(target)
            return False, error

        with self._lock:
            self._results[target] = value
            self._last_errors.pop(target, None)
        return True, ""

    def peek(self, task_id: str) -> tuple[bool, Any, int]:
        with self._lock:
            attempts = self._attempts.get(task_id, 0)
            if task_id in self._results:
                return True, self._results[task_id], attempts
            return False, None, attempts

    def peek_error(self, task_id: str) -> str:
        with self._lock:
            return self._last_errors.get(task_id, "")

    def clear(self, task_id: str) -> None:
        with self._lock:
            self._expect.pop(task_id, None)
            self._results.pop(task_id, None)
            self._attempts.pop(task_id, None)
            self._last_errors.pop(task_id, None)
            self._on_exhausted.pop(task_id, None)
            self._exhausted.discard(task_id)

    def _interrupt_exhausted(self, task_id: str) -> None:
        with self._lock:
            if task_id in self._exhausted:
                return
            self._exhausted.add(task_id)
            callback = self._on_exhausted.get(task_id)
        if callback is not None:
            try:
                callback()
            except Exception:
                pass


_BROKER = _StructuredOutputBroker()
_REGISTRY_LOCK = threading.RLock()
_REGISTRY_USERS = 0
_REGISTRY_OWNED = False


@contextmanager
def structured_output_tool_scope() -> Iterator[None]:
    """Expose the internal tool only while workflow schema children need it."""
    global _REGISTRY_USERS, _REGISTRY_OWNED

    registry = _tool_registry()
    with _REGISTRY_LOCK:
        if _REGISTRY_USERS == 0:
            existing = registry.get_entry(STRUCTURED_OUTPUT_TOOL_NAME)
            if existing is None:
                registry.register(
                    name=STRUCTURED_OUTPUT_TOOL_NAME,
                    toolset=STRUCTURED_OUTPUT_TOOLSET,
                    schema=STRUCTURED_OUTPUT_TOOL_SCHEMA,
                    handler=structured_output_handler,
                    description="Return structured output in the requested format.",
                )
                existing = registry.get_entry(STRUCTURED_OUTPUT_TOOL_NAME)
                _REGISTRY_OWNED = True
            else:
                _REGISTRY_OWNED = False
            if existing is None or existing.handler is not structured_output_handler:
                raise RuntimeError(
                    "structured_output tool name is already registered by another tool"
                )
        _REGISTRY_USERS += 1

    try:
        yield
    finally:
        with _REGISTRY_LOCK:
            _REGISTRY_USERS = max(0, _REGISTRY_USERS - 1)
            if _REGISTRY_USERS == 0 and _REGISTRY_OWNED:
                registry.deregister(STRUCTURED_OUTPUT_TOOL_NAME)
                _REGISTRY_OWNED = False


def set_current_child_task_id(task_id: str) -> contextvars.Token[str]:
    return _CURRENT_CHILD_TASK_ID.set(task_id)


def reset_current_child_task_id(token: contextvars.Token[str]) -> None:
    _CURRENT_CHILD_TASK_ID.reset(token)


@contextmanager
def child_task_id_scope(task_id: str) -> Iterator[None]:
    token = _CURRENT_CHILD_TASK_ID.set(task_id)
    try:
        yield
    finally:
        _CURRENT_CHILD_TASK_ID.reset(token)


def register_expectation(
    task_id: str,
    schema: dict[str, Any],
    on_exhausted: Callable[[], Any] | None = None,
) -> None:
    _BROKER.register(task_id, schema, on_exhausted)


def peek_result(task_id: str) -> tuple[bool, Any, int]:
    target = str(task_id or "").strip() or _CURRENT_CHILD_TASK_ID.get("")
    return _BROKER.peek(target)


def peek_error(task_id: str) -> str:
    target = str(task_id or "").strip() or _CURRENT_CHILD_TASK_ID.get("")
    return _BROKER.peek_error(target)


def clear_expectation(task_id: str) -> None:
    target = str(task_id or "").strip() or _CURRENT_CHILD_TASK_ID.get("")
    _BROKER.clear(target)
    if _CURRENT_CHILD_TASK_ID.get("") == target:
        _CURRENT_CHILD_TASK_ID.set("")


def structured_output_handler(args: Any, *, task_id: str | None = None, **kwargs: Any) -> str:
    """Validate and capture a workflow child's final structured value."""
    target_id = (
        str(task_id or "").strip()
        or str(kwargs.get("task_id") or "").strip()
        or _CURRENT_CHILD_TASK_ID.get("")
    )
    ok, error = _BROKER.submit(target_id, args)
    if ok:
        return STRUCTURED_OUTPUT_SUCCESS
    return tool_error(f"Output does not match required schema: {error}")


def _tool_registry() -> Any:
    from tools.registry import registry

    return registry


def _validation_errors(value: Any, schema: dict[str, Any]) -> list[str]:
    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

        validator = Draft202012Validator(schema)
        errors = sorted(
            validator.iter_errors(value),
            key=lambda error: (
                tuple(str(part) for part in error.absolute_path),
                str(error.validator),
                error.message,
            ),
        )
        return [_format_validation_error(error) for error in errors]
    except ImportError:
        pass
    except Exception as exc:
        return [f"root: {getattr(exc, 'message', str(exc))}"]

    try:
        validate_schema(value, schema)
    except Exception as exc:
        message = getattr(exc, "message", str(exc))
        prefix = "structured output did not match schema: "
        if message.startswith(prefix):
            message = message[len(prefix) :]
        return [_format_fallback_error(message)]
    return []


def _format_validation_error(error: Any) -> str:
    path = _json_pointer(error.absolute_path)
    validator = str(getattr(error, "validator", "") or "")
    validator_value = getattr(error, "validator_value", None)

    if validator == "required":
        missing = _missing_required_property(error.message)
        if missing:
            return f"{path}: must have required property '{missing}'"
    if validator == "type":
        expected = validator_value
        if isinstance(expected, list):
            expected = ",".join(str(item) for item in expected)
        return f"{path}: must be {expected}"
    if validator == "additionalProperties":
        return f"{path}: must NOT have additional properties"
    if validator == "enum":
        return f"{path}: must be equal to one of the allowed values"
    if validator == "const":
        return f"{path}: must be equal to constant"
    if validator == "minItems":
        return f"{path}: must NOT have fewer than {validator_value} items"
    if validator == "maxItems":
        return f"{path}: must NOT have more than {validator_value} items"
    if validator == "minLength":
        return f"{path}: must NOT have fewer than {validator_value} characters"
    if validator == "maxLength":
        return f"{path}: must NOT have more than {validator_value} characters"
    if validator == "minimum":
        return f"{path}: must be >= {validator_value}"
    if validator == "maximum":
        return f"{path}: must be <= {validator_value}"
    if validator == "pattern":
        return f'{path}: must match pattern "{validator_value}"'
    return f"{path}: {error.message}"


def _json_pointer(path: Iterable[Any]) -> str:
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
    return "/" + "/".join(parts) if parts else "root"


def _missing_required_property(message: str) -> str:
    if not message.startswith("'"):
        return ""
    _, _, remainder = message.partition("'")
    return remainder.partition("'")[0]


def _format_fallback_error(message: str) -> str:
    if message.startswith("$: "):
        message = message[3:]
    if message.startswith("missing required key "):
        return f"root: must have required property {message.removeprefix('missing required key ')}"
    if message.startswith("unexpected key "):
        return "root: must NOT have additional properties"
    if message.startswith("expected type "):
        return f"root: must be {message.removeprefix('expected type ')}"
    return message if message.startswith(("root:", "/")) else f"root: {message}"

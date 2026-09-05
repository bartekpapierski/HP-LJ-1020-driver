# SPDX-License-Identifier: GPL-2.0-or-later
"""Small dependency-free validator for the JSON Schema keywords used here."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any


class SchemaError(ValueError):
    pass


def _resolve(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise SchemaError(f"unsupported schema reference {reference!r}")
    current: Any = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise SchemaError(f"unresolved schema reference {reference!r}")
        current = current[part]
    if not isinstance(current, dict):
        raise SchemaError(f"schema reference is not an object {reference!r}")
    return current


def _matches_type(value: Any, expected: str) -> bool:
    return {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }.get(expected, lambda: False)()


def _is_valid(value: Any, schema: dict[str, Any], root: dict[str, Any]) -> bool:
    try:
        validate(value, schema, root=root)
    except SchemaError:
        return False
    return True


def validate(
    value: Any,
    schema: dict[str, Any],
    *,
    root: dict[str, Any] | None = None,
    path: str = "$",
) -> None:
    """Validate a value against the repository's supported schema subset."""
    root = schema if root is None else root
    if "$ref" in schema:
        validate(value, _resolve(root, schema["$ref"]), root=root, path=path)

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = [expected_type] if isinstance(expected_type, str) else expected_type
        if not isinstance(expected_types, list) or not any(
            isinstance(expected, str) and _matches_type(value, expected)
            for expected in expected_types
        ):
            raise SchemaError(f"{path}: expected type {expected_type!r}")
    if "const" in schema and value != schema["const"]:
        raise SchemaError(f"{path}: value does not match const")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path}: value is not in enum")

    if "oneOf" in schema:
        matches = sum(_is_valid(value, branch, root) for branch in schema["oneOf"])
        if matches != 1:
            raise SchemaError(f"{path}: expected exactly one matching schema")
    if "not" in schema and _is_valid(value, schema["not"], root):
        raise SchemaError(f"{path}: value matches a forbidden schema")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for field in required:
            if field not in value:
                raise SchemaError(f"{path}: missing required property {field!r}")
        properties = schema.get("properties", {})
        for field, child_schema in properties.items():
            if field in value:
                validate(value[field], child_schema, root=root, path=f"{path}.{field}")
        additional = schema.get("additionalProperties", True)
        for field in set(value) - set(properties):
            if additional is False:
                raise SchemaError(f"{path}: additional property {field!r}")
            if isinstance(additional, dict):
                validate(value[field], additional, root=root, path=f"{path}.{field}")
        if len(value) < schema.get("minProperties", 0):
            raise SchemaError(f"{path}: too few properties")
        if "propertyNames" in schema:
            for field in value:
                validate(field, schema["propertyNames"], root=root, path=f"{path} property name")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise SchemaError(f"{path}: too few items")
        if schema.get("uniqueItems"):
            identities = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(set(identities)) != len(identities):
                raise SchemaError(f"{path}: duplicate items")
        if "items" in schema:
            for index, item in enumerate(value):
                validate(item, schema["items"], root=root, path=f"{path}[{index}]")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise SchemaError(f"{path}: string is too short")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise SchemaError(f"{path}: string does not match pattern")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise SchemaError(f"{path}: invalid date-time") from error
            if parsed.tzinfo is None:
                raise SchemaError(f"{path}: date-time has no timezone")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaError(f"{path}: value is below minimum")

    for child_schema in schema.get("allOf", []):
        validate(value, child_schema, root=root, path=path)
    if "if" in schema and _is_valid(value, schema["if"], root) and "then" in schema:
        validate(value, schema["then"], root=root, path=path)

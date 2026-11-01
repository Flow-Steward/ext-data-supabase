"""Closed bounded input validation, before network access."""

import json
import math
import re


class Failure(Exception):
    def __init__(self, code, message, *, dispatched=False):
        super().__init__(message)
        self.code = code
        self.dispatched = dispatched


def require(condition, message, *, code="invalid_payload"):
    if not condition:
        raise Failure(code, message)


def text(value, maximum=128):
    require(
        isinstance(value, str)
        and 0 < len(value.encode()) <= maximum
        and all(ord(c) >= 32 for c in value),
        "Invalid bounded text.",
    )
    return value


def identifier(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value),
        "Invalid SQL identifier.",
    )
    return value


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, "Invalid bounded integer.")
    return value


def bounded_json(value, limit=256 * 1024, depth=0):
    require(depth <= 16, "JSON nesting exceeds limit.")
    if isinstance(value, dict):
        require(
            len(value) <= 1024 and all(isinstance(k, str) for k in value), "Invalid JSON object."
        )
        for v in value.values():
            bounded_json(v, limit, depth + 1)
    elif isinstance(value, list):
        require(len(value) <= 4096, "JSON array exceeds limit.")
        for v in value:
            bounded_json(v, limit, depth + 1)
    elif type(value) is int:
        require(
            abs(value) <= 9007199254740991, "Use text for integers outside safe JSON precision."
        )
    elif type(value) is float:
        require(math.isfinite(value), "Finite numbers are required.")
    else:
        require(value is None or type(value) in (str, bool), "Invalid JSON value.")
    if depth == 0:
        require(
            len(json.dumps(value, allow_nan=False).encode()) <= limit, "JSON exceeds byte limit."
        )
    return value


def connection_values(connection):
    from provider import KIND

    try:
        config, secrets = connection.get("config", {}), connection.get("secrets", {})
        require(isinstance(config, dict) and isinstance(secrets, dict), "Invalid connection.")
        keys = (
            {"base_id", "request_timeout_seconds"}
            if KIND == "airtable"
            else {"project_ref", "schema", "request_timeout_seconds"}
        )
        secret_keys = (
            {"personal_access_token"} if KIND == "airtable" else {"api_key", "access_token"}
        )
        require(set(config) <= keys and set(secrets) <= secret_keys, "Unknown connection field.")
        config = dict(config)
        config["request_timeout_seconds"] = integer(
            config.get("request_timeout_seconds", 15), 1, 30
        )
        if KIND == "airtable":
            require(
                re.fullmatch(r"app[A-Za-z0-9]{14}", text(config.get("base_id"))), "Invalid base ID."
            )
        else:
            require(
                re.fullmatch(r"[a-z0-9]{20}", text(config.get("project_ref"))),
                "Invalid project reference.",
            )
            config["schema"] = identifier(config.get("schema", "public"))
        for key in secret_keys:
            if key != "access_token" or key in secrets:
                text(secrets.get(key), 8192)
        return config, secrets
    except (Failure, ValueError, TypeError):
        raise Failure("invalid_connection", "Invalid provider connection or credentials.") from None

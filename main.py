"""Host-v2 project-scoped workflow entrypoint."""

import json
import sys
from flowsteward_extension_sdk import runtime_context_from_payload
from provider import KIND, WRITES
from validation import Failure, require, bounded_json, connection_values
from transport import Transport
from commands import prepare, result
from deadline import operation_deadline


def handle(payload):
    write = False
    transport = None
    try:
        bounded_json(payload)
        runtime_context_from_payload(payload)
        require(payload.get("mode") == "action", "An action invocation is required.")
        context = payload["runtime_context"]
        for key in ("account_id", "project_id"):
            require(
                isinstance(context.get(key), str) and bool(context[key].strip()),
                "Project-scoped account and project are required.",
            )
        require(type(context.get("test_mode", False)) is bool, "test_mode must be boolean.")
        action = payload.get("action") or {}
        name = action.get("action_id")
        args = action.get("input", {})
        require(isinstance(args, dict), "Input must be an object.")
        connection = (action.get("target") or {}).get("connection") or {}
        require(
            isinstance(connection, dict)
            and isinstance(args.get("connection_ref"), str)
            and bool(args["connection_ref"].strip())
            and connection.get("connection_id") == args["connection_ref"]
            and connection.get("connection_type") == KIND,
            "Select the matching project connection.",
            code="invalid_connection",
        )
        config, secrets = connection_values(connection)
        method, path, body, expected = prepare(name, args, config)
        write = name in WRITES
        if write:
            require(
                not context.get("test_mode"),
                "Writes are suppressed in test mode.",
                code="test_mode_suppressed",
            )
            claim = context.get("external_effect_id")
            require(
                isinstance(claim, str) and bool(claim.strip()) and len(claim) <= 512,
                "A durable external-effect claim is required.",
                code="effect_claim_required",
            )
        with operation_deadline(config["request_timeout_seconds"]):
            transport = Transport(config, secrets)
            value = result(name, transport.request(method, path, body), expected)
            bounded_json(value, 480 * 1024)
        return {"ok": True, "result": value, "errors": []}
    except Exception as exc:
        known = isinstance(exc, Failure)
        code = (
            exc.code
            if isinstance(exc, Failure)
            else "invalid_payload"
            if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError, RecursionError))
            else "provider_unavailable"
        )
        message = str(exc) if known else "Invalid input or provider request failed."
        uncertain = write and transport is not None and transport.dispatched
        return {
            "ok": False,
            "error_code": code,
            "error": message,
            "errors": [{"code": code, "message": message}],
            "retryable": False,
            "definitely_no_external_effect": not uncertain,
            "external_effect_status": "timeout_unknown" if uncertain else "not_applied",
        }


def main():
    try:
        raw = sys.stdin.buffer.read(256 * 1024 + 1)
        require(len(raw) <= 256 * 1024, "Input exceeds byte limit.")
        response = handle(json.loads(raw))
    except (ValueError, TypeError, Failure):
        response = {
            "ok": False,
            "error_code": "invalid_payload",
            "errors": [],
            "retryable": False,
            "definitely_no_external_effect": True,
            "external_effect_status": "not_applied",
        }
    print(json.dumps(response, allow_nan=False))
    return 0 if response["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline provider-contract and safety regressions; no credentials required."""

import io
from email.message import Message
from typing import Any
import json
from unittest.mock import patch
from urllib.error import HTTPError
import pytest
import main
import transport
from provider import KIND


def envelope(name=None, **args):
    air = KIND == "airtable"
    config = {"base_id": "appABCDEFGHIJKLMN"} if air else {"project_ref": "abcdefghijklmnopqrst"}
    secrets = {"personal_access_token": "test-secret"} if air else {"api_key": "eyJtest-secret"}
    return {
        "mode": "action",
        "contract_version": "extension_host_v2",
        "runtime_context": {
            "account_id": "account",
            "group_id": None,
            "for_each_id": None,
            "step_id": "step",
            "step_execution_id": "execution",
            "workflow_id": "workflow",
            "job_id": "job",
            "project_id": "project",
            "test_mode": False,
            "external_effect_id": "effect",
        },
        "action": {
            "action_id": name or ("list_records" if air else "list_rows"),
            "input": {"connection_ref": "conn", "table": "Tasks", **args},
            "target": {
                "connection": {
                    "connection_id": "conn",
                    "connection_type": KIND,
                    "config": config,
                    "secrets": secrets,
                }
            },
        },
    }


class Response:
    status = 200

    def __init__(self, value):
        self.raw = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n):
        return self.raw[:n]


def provider_value():
    return (
        {
            "records": [{"id": "recABCDEFGHIJKLMN", "fields": {"Name": "hello"}}],
            "offset": "opaque/next+token",
        }
        if KIND == "airtable"
        else [{"id": 123, "name": "hello"}]
    )


@pytest.fixture
def network():
    with (
        patch.object(transport, "resolve_pinned_ips", return_value=["1.1.1.1"]) as dns,
        patch.object(transport, "open_pinned_url", return_value=Response(provider_value())) as send,
    ):
        yield dns, send


def write_payload():
    return (
        envelope("create_records", records=[{"fields": {"Name": "hello"}}])
        if KIND == "airtable"
        else envelope("insert_rows", rows=[{"id": 123, "name": "hello"}])
    )


def test_read_contract(network):
    value = main.handle(envelope())
    assert value["ok"]
    assert value["result"]["count"] == 1
    req = network[1].call_args.args[0]
    assert req.method == "GET"
    assert (
        req.full_url.startswith("https://api.airtable.com/v0/")
        if KIND == "airtable"
        else req.full_url.startswith("https://abcdefghijklmnopqrst.supabase.co/rest/v1/")
    )
    assert network[1].call_count == 1


def test_create_contract(network):
    assert main.handle(write_payload())["ok"]
    req = network[1].call_args.args[0]
    assert req.method == "POST"
    assert json.loads(req.data)


def test_credentials_in_headers_only(network):
    assert main.handle(envelope())["ok"]
    req = network[1].call_args.args[0]
    assert "test-secret" not in req.full_url
    assert req.headers["Authorization"] == "Bearer " + (
        "test-secret" if KIND == "airtable" else "eyJtest-secret"
    )


@pytest.mark.parametrize("scope", ["account_id", "project_id"])
def test_scope_required(scope, network):
    p = envelope()
    del p["runtime_context"][scope]
    assert not main.handle(p)["ok"]
    network[1].assert_not_called()


@pytest.mark.parametrize("value", [1, "false", None, [], {}])
def test_test_mode_boolean(value, network):
    p = write_payload()
    p["runtime_context"]["test_mode"] = value
    assert not main.handle(p)["ok"]
    network[1].assert_not_called()


def test_test_mode_suppresses(network):
    p = write_payload()
    p["runtime_context"]["test_mode"] = True
    r = main.handle(p)
    assert r["error_code"] == "test_mode_suppressed"
    network[0].assert_not_called()


def test_claim_required(network):
    p = write_payload()
    del p["runtime_context"]["external_effect_id"]
    r = main.handle(p)
    assert r["error_code"] == "effect_claim_required"
    network[0].assert_not_called()


@pytest.mark.parametrize("key,value", [("connection_id", "other"), ("connection_type", "other")])
def test_connection_match(key, value, network):
    p = envelope()
    p["action"]["target"]["connection"][key] = value
    assert main.handle(p)["error_code"] == "invalid_connection"
    network[0].assert_not_called()


def test_unknown_config_blocks_urls(network):
    p = envelope()
    p["action"]["target"]["connection"]["config"]["base_url"] = "https://attacker.invalid"
    assert main.handle(p)["error_code"] == "invalid_connection"
    network[0].assert_not_called()


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "::1", "169.254.169.254"])
def test_private_dns_blocked(address, network):
    network[0].return_value = [address]
    r = main.handle(write_payload())
    assert r["error_code"] == "network_blocked"
    assert r["definitely_no_external_effect"]
    network[1].assert_not_called()


def test_mixed_dns_blocked(network):
    network[0].return_value = ["1.1.1.1", "127.0.0.1"]
    assert main.handle(envelope())["error_code"] == "network_blocked"
    network[1].assert_not_called()


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_no_retry_unknown_write(status, network):
    network[1].side_effect = HTTPError(
        "https://provider", status, "test-secret", Message(), io.BytesIO(b"test-secret")
    )
    r = main.handle(write_payload())
    assert not r["ok"]
    assert r["external_effect_status"] == "timeout_unknown"
    assert not r["retryable"]
    assert "test-secret" not in json.dumps(r)
    assert network[1].call_count == 1


def test_timeout_unknown(network):
    network[1].side_effect = TimeoutError("test-secret")
    r = main.handle(write_payload())
    assert r["external_effect_status"] == "timeout_unknown"
    assert "test-secret" not in json.dumps(r)


def test_malformed_write_response_unknown(network):
    response = Response(None)
    response.raw = b"not json"
    network[1].return_value = response
    r = main.handle(write_payload())
    assert r["error_code"] == "invalid_provider_response"
    assert not r["definitely_no_external_effect"]


def test_partial_write_unknown(network):
    network[1].return_value = Response({"records": []} if KIND == "airtable" else [])
    r = main.handle(write_payload())
    assert r["error_code"] == "invalid_provider_response"
    assert r["external_effect_status"] == "timeout_unknown"


def test_oversize_write_unknown(network):
    response = Response(None)
    response.raw = b"x" * (480 * 1024 + 1)
    network[1].return_value = response
    r = main.handle(write_payload())
    assert r["error_code"] == "response_too_large"
    assert not r["definitely_no_external_effect"]


def test_nonfinite_rejected_before_io(network):
    p = write_payload()
    p["action"]["input"]["extra"] = float("nan")
    assert not main.handle(p)["ok"]
    network[0].assert_not_called()


def test_unsafe_integer_rejected(network):
    p = write_payload()
    p["action"]["input"]["extra"] = 9007199254740992
    assert not main.handle(p)["ok"]
    network[0].assert_not_called()


def test_nested_bound(network):
    p = envelope()
    v: Any = []
    for _ in range(20):
        v = [v]
    p["action"]["input"]["extra"] = v
    assert not main.handle(p)["ok"]
    network[0].assert_not_called()


def test_unknown_action(network):
    assert not main.handle(envelope("drop_database"))["ok"]
    network[0].assert_not_called()


def test_unknown_input(network):
    assert not main.handle(envelope(url="https://attacker.invalid"))["ok"]
    network[0].assert_not_called()


def test_filters_projection_pagination(network):
    assert main.handle(
        envelope(
            filters=[{"column": "id", "operator": "eq", "value": 123}],
            select=["id", "name"],
            limit=10,
            offset=20,
        )
    )["ok"]
    req = network[1].call_args.args[0]
    assert "id=eq.123" in req.full_url
    assert "select=id%2Cname" in req.full_url
    assert "offset=20" in req.full_url
    assert req.headers["Accept-profile"] == "public"


def test_in_quotes_are_escaped(network):
    assert main.handle(
        envelope(filters=[{"column": "name", "operator": "in", "value": ["a,b", "c)"]}])
    )["ok"]
    req = network[1].call_args.args[0]
    assert "%22a%2Cb%22" in req.full_url


def test_update(network):
    assert main.handle(
        envelope(
            "update_rows",
            filters=[{"column": "id", "operator": "eq", "value": 123}],
            values={"name": "new"},
        )
    )["ok"]
    req = network[1].call_args.args[0]
    assert req.method == "PATCH"
    assert req.headers["Content-profile"] == "public"


def test_delete(network):
    assert main.handle(
        envelope("delete_rows", filters=[{"column": "id", "operator": "eq", "value": 123}])
    )["ok"]
    assert network[1].call_args.args[0].method == "DELETE"


def test_upsert(network):
    assert main.handle(
        envelope("upsert_rows", rows=[{"id": 123, "name": "hello"}], on_conflict=["id"])
    )["ok"]
    req = network[1].call_args.args[0]
    assert "resolution=merge-duplicates" in req.headers["Prefer"]
    assert "on_conflict=id" in req.full_url


@pytest.mark.parametrize("action", ["update_rows", "delete_rows"])
def test_unfiltered_mutation_rejected(action, network):
    p = envelope(action, filters=[])
    if action == "update_rows":
        p["action"]["input"]["values"] = {"name": "oops"}
    assert not main.handle(p)["ok"]
    network[0].assert_not_called()


@pytest.mark.parametrize(
    "table", ["../../rpc/function", "https://attacker.invalid", "items?select=*", "rpc/test"]
)
def test_invalid_table(table, network):
    assert not main.handle(envelope(table=table))["ok"]
    network[0].assert_not_called()


def test_new_secret_key_not_used_as_jwt(network):
    p = envelope()
    p["action"]["target"]["connection"]["secrets"]["api_key"] = "sb_secret_test"
    assert main.handle(p)["ok"]
    req = network[1].call_args.args[0]
    assert "Authorization" not in req.headers
    assert req.headers["Apikey"] == "sb_secret_test"


def test_explicit_access_token(network):
    p = envelope()
    p["action"]["target"]["connection"]["secrets"]["access_token"] = "jwt-user"
    assert main.handle(p)["ok"]
    assert network[1].call_args.args[0].headers["Authorization"] == "Bearer jwt-user"


def test_operator_injection_rejected(network):
    assert not main.handle(envelope(filters=[{"column": "id", "operator": "or", "value": "true"}]))[
        "ok"
    ]
    network[0].assert_not_called()


@pytest.mark.parametrize("phase", ["dns", "body"])
def test_total_wall_clock_deadline(phase, network):
    import time
    import signal

    p = write_payload()
    p["action"]["target"]["connection"]["config"]["request_timeout_seconds"] = 1
    previous = signal.getsignal(signal.SIGALRM)
    if phase == "dns":

        def slow_dns(*args, **kwargs):
            time.sleep(3)
            return ["1.1.1.1"]

        network[0].side_effect = slow_dns
    else:
        response = Response(provider_value())

        def drip(n):
            time.sleep(3)
            return response.raw

        network[1].return_value = response
        network[1].return_value.read = drip
    started = time.monotonic()
    r = main.handle(p)
    elapsed = time.monotonic() - started
    assert elapsed < 1.8
    assert r["error_code"] == "timeout"
    assert r["external_effect_status"] == ("not_applied" if phase == "dns" else "timeout_unknown")
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_canonical_apache_license():
    import hashlib
    from pathlib import Path

    assert (
        hashlib.sha256((Path(__file__).parents[1] / "LICENSE").read_bytes()).hexdigest()
        == "58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd"
    )


@pytest.mark.parametrize(
    "column", ["select", "columns", "on_conflict", "order", "limit", "offset", "and", "or"]
)
@pytest.mark.parametrize("name", ["update_rows", "delete_rows"])
@pytest.mark.parametrize("mode", ["normal", "test_mode", "missing_claim"])
def test_reserved_query_control_is_never_mutation_filter(column, name, mode, network):
    p = envelope(name, filters=[{"column": column, "operator": "eq", "value": 1}])
    if name == "update_rows":
        p["action"]["input"]["values"] = {"name": "changed"}
    if mode == "test_mode":
        p["runtime_context"]["test_mode"] = True
    if mode == "missing_claim":
        del p["runtime_context"]["external_effect_id"]
    result = main.handle(p)
    assert result["error_code"] == "invalid_payload"
    assert result["definitely_no_external_effect"]
    network[0].assert_not_called()
    network[1].assert_not_called()


@pytest.mark.parametrize(
    "operator,value,encoded", [("eq", "", "name=eq."), ("in", [""], "name=in.%28%22%22%29")]
)
def test_empty_filter_text_is_preserved(operator, value, encoded, network):
    assert main.handle(
        envelope(filters=[{"column": "name", "operator": operator, "value": value}])
    )["ok"]
    assert encoded in network[1].call_args.args[0].full_url


def test_previous_alarm_timer_is_restored():
    import signal
    from deadline import operation_deadline

    original = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)

    def previous(signum, frame):
        raise AssertionError("Unrelated timer fired unexpectedly")

    try:
        signal.signal(signal.SIGALRM, previous)
        signal.setitimer(signal.ITIMER_REAL, 5, 2)
        with operation_deadline(1):
            pass
        remaining, interval = signal.getitimer(signal.ITIMER_REAL)
        assert 4 < remaining <= 5
        assert interval == 2
        assert signal.getsignal(signal.SIGALRM) == previous
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, original)
        signal.setitimer(signal.ITIMER_REAL, *old_timer)

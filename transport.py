"""Fixed HTTPS origins, pinned public DNS, one bounded attempt per operation."""

import ipaddress
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request
from flowsteward_extension_sdk import open_pinned_url, resolve_pinned_ips
from provider import KIND
from validation import Failure, require


class Transport:
    def __init__(self, config, secrets):
        self.config, self.secrets = config, secrets
        self.host = (
            "api.airtable.com" if KIND == "airtable" else config["project_ref"] + ".supabase.co"
        )
        self.deadline = time.monotonic() + config["request_timeout_seconds"]
        self.dispatched = False

    def request(self, method, path, body=None):
        try:
            ips = tuple(resolve_pinned_ips(self.host, port=443, purpose=KIND + " API"))
            require(
                bool(ips) and all(ipaddress.ip_address(ip).is_global for ip in ips),
                "Provider DNS is blocked.",
                code="network_blocked",
            )
        except (ValueError, OSError):
            raise Failure("network_blocked", "Provider DNS is blocked.") from None
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "Operation deadline exceeded.", code="timeout")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if KIND == "airtable":
            headers["Authorization"] = "Bearer " + self.secrets["personal_access_token"]
        else:
            key = self.secrets["api_key"]
            headers["apikey"] = key
            token = self.secrets.get("access_token")
            if token or key.startswith("eyJ"):
                headers["Authorization"] = "Bearer " + (token or key)
            headers["Accept-Profile" if method == "GET" else "Content-Profile"] = self.config[
                "schema"
            ]
            headers["Prefer"] = "return=representation" + (
                ",resolution=merge-duplicates"
                if method == "POST" and "on_conflict=" in path
                else ""
            )
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        request = Request("https://" + self.host + path, data=data, method=method, headers=headers)
        self.dispatched = method != "GET"
        try:
            with open_pinned_url(
                request, timeout_seconds=remaining, purpose=KIND + " API", pinned_ips=ips
            ) as response:
                raw = response.read(480 * 1024 + 1)
                require(
                    len(raw) <= 480 * 1024,
                    "Provider result exceeds inline budget.",
                    code="response_too_large",
                )
                require(
                    response.status in (200, 201, 204, 206),
                    "Unexpected provider status.",
                    code="invalid_provider_response",
                )
        except HTTPError as exc:
            code = {
                400: "invalid_payload",
                401: "authentication_failed",
                403: "authentication_failed",
                404: "not_found",
                409: "conflict",
                422: "invalid_payload",
                429: "rate_limited",
            }.get(exc.code, "provider_unavailable")
            raise Failure(
                code, f"Provider returned HTTP {exc.code}.", dispatched=self.dispatched
            ) from None
        except (OSError, URLError, ValueError):
            raise Failure(
                "provider_unavailable", "Provider request failed.", dispatched=self.dispatched
            ) from None
        try:
            return json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            raise Failure(
                "invalid_provider_response",
                "Provider returned invalid JSON.",
                dispatched=self.dispatched,
            ) from None

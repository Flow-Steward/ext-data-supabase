"""Structured PostgREST table operations; no RPC or arbitrary query strings."""

import json
from urllib.parse import urlencode
from validation import require, identifier, integer, text


def scalar(value):
    require(
        value is None or type(value) in (str, int, float, bool), "Filter values must be scalar."
    )
    if isinstance(value, str):
        return text(value, 4096)
    return json.dumps(value, allow_nan=False)


def filter_pairs(filters):
    require(isinstance(filters, list) and len(filters) <= 20, "Requires bounded filter array.")
    pairs = []
    for f in filters:
        require(
            isinstance(f, dict) and set(f) == {"column", "operator", "value"},
            "Filter requires column, operator and value.",
        )
        column = identifier(f["column"])
        op = f["operator"]
        v = f["value"]
        require(
            op in {"eq", "neq", "gt", "gte", "lt", "lte", "in", "is", "like"},
            "Unsupported filter operator.",
        )
        if op == "in":
            require(
                isinstance(v, list) and 1 <= len(v) <= 100, "IN requires 1 to 100 scalar values."
            )
            # PostgREST quoted values protect commas, parentheses, quotes and backslashes.
            encoded = []
            for item in v:
                raw = scalar(item)
                encoded.append(
                    '"' + raw.replace("\\", "\\\\").replace('"', '\\"') + '"'
                    if isinstance(item, str)
                    else raw
                )
            value = "(" + ",".join(encoded) + ")"
        elif op == "is":
            require(v is None or type(v) is bool, "IS requires null or boolean.")
            value = scalar(v)
        else:
            value = scalar(v)
        pairs.append((column, op + "." + value))
    return pairs


def row(value):
    require(
        isinstance(value, dict) and 1 <= len(value) <= 128, "Requires nonempty bounded row object."
    )
    for key in value:
        identifier(key)


def prepare(name, args, config):
    fields = {
        "list_rows": {"filters", "select", "limit", "offset"},
        "insert_rows": {"rows"},
        "upsert_rows": {"rows", "on_conflict"},
        "update_rows": {"filters", "values"},
        "delete_rows": {"filters"},
    }
    require(name in fields, "Unknown action.")
    require(set(args) <= fields[name] | {"table", "connection_ref"}, "Unknown input field.")
    table = identifier(args.get("table"))
    path = "/rest/v1/" + table
    body = None
    query = []
    expected: object = None
    if name == "list_rows":
        query = filter_pairs(args.get("filters", []))
        select = args.get("select")
        if select is not None:
            require(
                isinstance(select, list) and 1 <= len(select) <= 64,
                "Select requires 1 to 64 columns.",
            )
            query.append(("select", ",".join(identifier(v) for v in select)))
        query += [
            ("limit", integer(args.get("limit", 100), 1, 100)),
            ("offset", integer(args.get("offset", 0), 0, 1000000)),
        ]
        method = "GET"
        expected = args.get("limit", 100)
    elif name in {"update_rows", "delete_rows"}:
        query = filter_pairs(args.get("filters"))
        require(bool(query), "Mutations require at least one explicit filter.")
        method = "PATCH" if name == "update_rows" else "DELETE"
        if method == "PATCH":
            body = args.get("values")
            row(body)
    else:
        body = args.get("rows")
        require(isinstance(body, list) and 1 <= len(body) <= 100, "Requires 1 to 100 rows.")
        for value in body:
            row(value)
        require(
            all(set(v) == set(body[0]) for v in body), "Batch rows must have identical columns."
        )
        method = "POST"
        expected = len(body)
        if name == "upsert_rows":
            conflict = args.get("on_conflict")
            require(
                isinstance(conflict, list) and 1 <= len(conflict) <= 8,
                "Explicit conflict columns are required.",
            )
            require(len(set(conflict)) == len(conflict), "Duplicate conflict columns.")
            for column in conflict:
                identifier(column)
                require(
                    all(column in r and r[column] is not None for r in body),
                    "Every row requires conflict key values.",
                )
            query.append(("on_conflict", ",".join(conflict)))
    if query:
        path += "?" + urlencode(query)
    return method, path, body, expected


def result(name, value, expected):
    require(
        isinstance(value, list) and len(value) <= 100 and all(isinstance(r, dict) for r in value),
        "Invalid or excessive provider row result.",
        code="invalid_provider_response",
    )
    if name in {"insert_rows", "upsert_rows"}:
        require(
            len(value) == expected, "Incomplete write result.", code="invalid_provider_response"
        )
    if name == "list_rows":
        require(
            len(value) <= expected,
            "Provider exceeded requested row limit.",
            code="invalid_provider_response",
        )
    return {"rows": value, "count": len(value)}

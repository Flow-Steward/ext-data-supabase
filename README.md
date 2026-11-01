# Supabase workflow extension

Standalone Flow Steward host-v2 table CRUD adapter, extension ID `flowsteward.supabase`.
Python 3.12+, standard library plus the host-provided `flowsteward-extension-sdk==0.4.0`. No native drivers or runtime dependency downloads. No triggers, webhooks or realtime subscriptions.

Choose a project connection and pass its ID as `connection_ref`. Account/project context, matching connection type and reference are mandatory. Mutations require a durable `external_effect_id` and are suppressed in test mode before DNS or HTTP. The selected provider credential authorizes direct table access; record IDs and row values are not rewritten with project prefixes.

Only the fixed provider HTTPS origin is reachable. DNS is pinned with SDK 0.4 and every address must be public, including when host private networking is allowed. Redirect handling belongs to the SDK pinned opener. Caller URLs are rejected. Credentials are headers only; provider errors and bodies are not reflected in errors.

Every invocation makes one HTTP attempt within a shared 1–30 second deadline. No retries or automatic page loops. A write dispatched before timeout, malformed/partial response, oversized result or HTTP error reports `timeout_unknown`; inspect provider state before reconciling or retrying. Effect claims do not create provider-side deduplication. Output is capped at 480 KiB. JSON nesting is capped at 16; integers outside ±9007199254740991 must be strings.

## Operations

Connection config: `project_ref` (20 lowercase alphanumerics), optional `schema` (default public, SQL identifier), optional `request_timeout_seconds` (default 15). Secret: `api_key`; optional `access_token` JWT. The key is always `apikey`; legacy JWT keys also become Bearer when no access token is supplied. New `sb_secret_` / `sb_publishable_` keys are not sent as JWTs. Service-role credentials may bypass row-level security; select the appropriate credential for the workflow.

- `list_rows`: table, optional `filters`, safe column-name `select` array, `limit` 1–100 and `offset` 0–1000000.
- `insert_rows`, `upsert_rows`: 1–100 nonempty row objects with identical column sets. Upsert requires explicit `on_conflict` columns present and nonnull in every row.
- `update_rows`: nonempty `values` and at least one filter.
- `delete_rows`: at least one filter. There is no unfiltered mutation switch.

Filters are arrays of `{column, operator, value}` with whitelisted `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `is`, `like`. IN accepts up to 100 scalar values with PostgREST quote escaping. IS accepts JSON null/boolean. Columns, tables and schema are closed identifiers, not expressions. Nested JSON column values remain JSON. Provider responses with over 100 rows fail closed; filtered update/delete can affect more rows than the bounded output, so use unique key filters when editing individual rows.

Uses `https://{project_ref}.supabase.co/rest/v1/{table}`, schema profile headers, `Prefer: return=representation`, and `resolution=merge-duplicates` for upsert. Scope is database table records; no Storage, Auth admin, SQL or RPC APIs.

Official API contracts checked 2026-11-01 through Context7: [Supabase API snippets](https://github.com/supabase/supabase/blob/master/apps/studio/components/interfaces/Docs/Snippets.ts), [custom schemas](https://supabase.com/docs/guides/api/using-custom-schemas), [JWT authorization](https://supabase.com/docs/guides/auth/jwts), [API keys](https://supabase.com/docs/guides/api/api-keys).

## Verification and release

Tests use mocked pinned HTTP and validate CRUD requests, pagination, input limits, credentials, project context, effect claims, write ambiguity and public DNS enforcement. No cloud credentials were supplied: live provider behavior is not verified.

From a Flow Steward checkout run `lint.sh --checks extension-static,extension-tests --extension-root <checkout>` in the disposable audit container. Development dependencies install offline from SDK dev wheels plus audit image site packages.

Build `python scripts/package_extension.py --runtime-target linux-amd64` and again with `linux-arm64`. Both deterministic pure Python ZIPs contain `.fs-package.yaml` with only `runtime_target`; `native_executable` is omitted. Source is architecture independent. Archive checksums accompany releases.

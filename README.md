# Supabase workflow extension

Flow Steward extension `flowsteward.supabase`, version **1.0.3**.

Automate Supabase table records from Flow Steward without writing a custom HTTP integration. List rows with column selection, filters, a limit and an offset; insert batches; upsert against explicit conflict columns; or update and delete rows selected by filters. The extension uses Supabase’s PostgREST table API and supports comparison, membership, null/boolean and LIKE filters. Nested JSON column values remain JSON.

For example, read new requests from a table, enrich them with another workflow step, then upsert a result by its unique external identifier. Update an approval status using a record ID filter, or delete matching records as part of an authorized cleanup workflow. Inserts and upserts accept up to 100 rows with matching column sets; upserts require the chosen conflict columns to be present and nonnull.

Configure a hosted Supabase project reference, schema and API key, with an optional access-token JWT. The selected credentials determine table access and row-level security; service-role credentials can bypass those policies. Update and delete require filters, but those filters can still match many rows. The extension covers table records rather than Storage, Auth administration, SQL, RPC, webhooks or realtime subscriptions.

Create a project Supabase connection with the hosted project reference, optional schema and secret API key; add an access-token JWT when the workflow requires that identity. Ensure the schema/table is exposed through the Data API and the chosen credentials and row-level security policies permit the intended operations.

Choose a project connection and pass its ID as `connection_ref`. Account/project context, matching connection type and reference are mandatory. Mutations require a durable `external_effect_id` and are suppressed in test mode before DNS or HTTP. The selected provider credential authorizes direct table access; record IDs and row values are not rewritten with project prefixes.

Only the fixed provider HTTPS origin is reachable. DNS is pinned with SDK 0.4 and every address must be public, including when host private networking is allowed. Redirect handling belongs to the SDK pinned opener. Caller URLs are rejected. Credentials are headers only; provider errors and bodies are not reflected in errors.

Every invocation makes one HTTP attempt within a shared 1–30 second Linux wall-clock deadline. A restored SIGALRM timer bounds DNS, response headers, body reads and decoding; the subprocess runs on its main thread. No retries or automatic page loops. A write dispatched before timeout, malformed/partial response, oversized result or HTTP error reports `timeout_unknown`; inspect provider state before reconciling or retrying. Effect claims do not create provider-side deduplication. Output is capped at 480 KiB. JSON nesting is capped at 16; integers outside ±9007199254740991 must be strings.

## Operations

Connection config: `project_ref` (20 lowercase alphanumerics), optional `schema` (default public, SQL identifier), optional `request_timeout_seconds` (default 15). Secret: `api_key`; optional `access_token` JWT. The key is always `apikey`; legacy JWT keys also become Bearer when no access token is supplied. New `sb_secret_` / `sb_publishable_` keys are not sent as JWTs. Service-role credentials may bypass row-level security; select the appropriate credential for the workflow.

- `list_rows`: table, optional `filters`, safe column-name `select` array, `limit` 1–100 and `offset` 0–1000000.
- `insert_rows`, `upsert_rows`: 1–100 nonempty row objects with identical column sets. Upsert requires explicit `on_conflict` columns present and nonnull in every row.
- `update_rows`: nonempty `values` and at least one filter.
- `delete_rows`: at least one filter. There is no unfiltered mutation switch.

Filters are arrays of `{column, operator, value}` with whitelisted `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `is`, `like`. IN accepts up to 100 scalar values with PostgREST quote escaping. IS accepts JSON null/boolean. Columns, tables and schema are closed identifiers, not expressions. Filter columns also reject all reserved PostgREST query controls (`select`, `columns`, `on_conflict`, `order`, `limit`, `offset`, `and`, `or`) before effect claim or test-mode processing, so controls cannot stand in for a mutation WHERE clause. Empty strings are valid equality/IN filter data. Nested JSON column values remain JSON. Provider responses with over 100 rows fail closed; filtered update/delete can affect more rows than the bounded output, so use unique key filters when editing individual rows.

Uses `https://{project_ref}.supabase.co/rest/v1/{table}`, schema profile headers, `Prefer: return=representation`, and `resolution=merge-duplicates` for upsert. Scope is database table records; no Storage, Auth admin, SQL or RPC APIs.

Official API contracts checked 2026-11-01 through Context7 and the [PostgREST 13 query parser](https://github.com/PostgREST/postgrest/blob/v13.0.8/src/PostgREST/ApiRequest/QueryParams.hs): [Supabase API snippets](https://github.com/supabase/supabase/blob/master/apps/studio/components/interfaces/Docs/Snippets.ts), [custom schemas](https://supabase.com/docs/guides/api/using-custom-schemas), [JWT authorization](https://supabase.com/docs/guides/auth/jwts), [API keys](https://supabase.com/docs/guides/api/api-keys).

## Verification and release

Tests use mocked pinned HTTP and validate CRUD requests, pagination, input limits, credentials, project context, effect claims, write ambiguity, complete wall-clock deadlines and public DNS enforcement. The canonical Apache-2.0 license bytes are regression checked. No cloud credentials were supplied: live provider behavior is not verified.

From a Flow Steward checkout run `lint.sh --checks extension-static,extension-tests --extension-root <checkout>` in the disposable audit container. Development dependencies install offline from SDK dev wheels plus audit image site packages.

Build `python scripts/package_extension.py --runtime-target linux-amd64` and again with `linux-arm64`. Both deterministic pure Python ZIPs contain `.fs-package.yaml` with only `runtime_target`; `native_executable` is omitted. Source is architecture independent. Archive checksums accompany releases.

## Automated releases

CI runs on pull requests and pushes to `main`. Official releases run through the
pinned shared GitHub Actions workflow using `.github/release-config.json` to test,
package both Linux runtime targets, and publish the release assets automatically.
Manual ZIP uploads are not part of the release process.

After merging the version **1.0.3** update into `main`, create and push its tag:

```sh
git switch main
git pull --ff-only
git tag -a v1.0.3 -m "Release v1.0.3"
git push origin v1.0.3
```

To rerun the workflow for an existing tag without moving it:

```sh
gh workflow run release.yml --ref main -f tag=v1.0.3
```

The manifest remains the source for release identity and catalog descriptions.
The shared workflow installs the verified first-party SDK wheel before test
dependencies. Where native payloads are absent from source, the recipe restores
only the listed missing files from checksum-pinned published archives; the source
packager still verifies their provenance before packaging.

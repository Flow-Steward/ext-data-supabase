# Supabase workflow actions

Configure a Supabase project connection with its 20-character project_ref, exposed PostgREST schema (public by default), and API key in connection secrets. The connector derives the HTTPS project URL; an optional access_token secret supplies a user bearer token. The key and database policies determine accessible tables and rows; grant the permissions required by the action. Select that connection and an existing table. These actions use structured PostgREST inputs, not SQL or RPC. Split batches above 100 rows.

Action names below match the workflow builder. IDs in parentheses remain compatible with saved workflows. Examples show field values; bind values from earlier steps as needed.

## Choose and configure an action

### Read filtered table rows (`list_rows`)

Read up to 100 Supabase rows with optional column selection and filters. Use an offset for another page; access follows the connection credentials and database policies.

```json
{
  "table": "orders",
  "filters": [
    {
      "column": "id",
      "operator": "eq",
      "value": 1042
    }
  ],
  "select": [
    "id",
    "status"
  ]
}
```

### Insert new table rows (`insert_rows`)

Insert 1–100 rows into a Supabase table. Every row in a batch must contain the same column names.

```json
{
  "table": "orders",
  "rows": [
    {
      "id": 1042,
      "status": "approved"
    }
  ]
}
```

### Insert or update rows by unique columns (`upsert_rows`)

Save 1–100 rows using explicit conflict columns backed by a database unique constraint. Every row must include non-null conflict values.

```json
{
  "table": "orders",
  "rows": [
    {
      "id": 1042,
      "status": "approved"
    }
  ],
  "on_conflict": [
    "id"
  ]
}
```

### Update rows matching filters (`update_rows`)

Patch the supplied columns on every matching row. At least one explicit filter is required; omitted columns are preserved.

```json
{
  "table": "orders",
  "filters": [
    {
      "column": "id",
      "operator": "eq",
      "value": 1042
    }
  ],
  "values": {
    "status": "approved"
  }
}
```

### Delete rows matching filters (`delete_rows`)

Delete every row matching the supplied filters. At least one explicit filter is required; inspect matches with Read filtered table rows first.

```json
{
  "table": "orders",
  "filters": [
    {
      "column": "id",
      "operator": "eq",
      "value": 1042
    }
  ]
}
```

## Requirements and result handling

Filters combine with AND. Supported operators are `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `in`, `is` and `like`; `in` takes an array, `is` takes null or boolean. Update/delete require a nonempty filter and affect every match. Preview the filter with the read action first. Upsert needs an existing unique constraint covering the conflict columns and non-null conflict values in every row. Results are in `result.rows` and `result.count`.

Workflow write actions are suppressed in test mode. Read/search actions still read the configured service. If a write fails after dispatch, inspect the service before repeating it; the write may already have applied.

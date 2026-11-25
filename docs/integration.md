# Replenishment batch integration

The batch client models the caller in a local replenishment workflow. It
requests quantities in one batch and emits JSON for a downstream planner.

1. Check `GET /health` for readiness.
2. Read `GET /v1/catalog` for the available forecast week's Monday date, SKU
   list, current method, and model version.
3. Send the target week and between one and 25 distinct SKUs to
   `POST /v1/forecasts`. Results preserve request order, use units sold, and
   include the snapshot week and model version for traceability. The local
   OpenAPI contract is available at `/openapi.json`.

Example request:

```json
{"forecast_week": "2011-12-05", "skus": ["85123A", "84879"]}
```

Observed response for the published dataset snapshot:

```json
{
  "history_through_week": "2011-11-28",
  "forecast_week": "2011-12-05",
  "model_version": "b3a55adf1d821d0a",
  "method": "four_week_mean",
  "forecasts": [
    {"sku": "85123A", "units": 888.75},
    {"sku": "84879", "units": 1266.0}
  ]
}
```

A stale forecast week, duplicate SKU, unsupported SKU, or invalid payload gets
HTTP 422. The command exits with code 1 and writes the error to stderr for HTTP
errors, invalid responses, or connection failures. A failed execution leaves
stdout empty so downstream jobs can distinguish it from a successful batch.

As a smoke test, run the README example with `99999` as the only SKU and check for
HTTP 422. Stop the service and repeat the successful example to check that the
client reports a connection failure. A running instance loads its snapshot and
model once at startup. Restart it after rebuilding the artifacts. It rejects an
artifact built against a different weekly panel.

An Apple Silicon loopback run with a warm, persistent connection and 25 SKUs
per request measured **0.77 ms median** and **0.91 ms p95** over 100 sequential
requests after 10 warmups. The result describes that local baseline run.

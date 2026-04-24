# Datadog export

This document describes how the Titan exporter service pushes and pulls data from Datadog, covering metrics submission, dashboard export, and monitor export.

## Overview

The exporter integrates with the Datadog API v1/v2 to support three categories of operation:

| Operation | Direction | Datadog endpoint |
|-----------|-----------|------------------|
| Metric series | Titan → Datadog | `POST /api/v2/series` |
| Dashboard export | Datadog → Titan | `GET /api/v1/dashboard/{id}` |
| Monitor export | Datadog → Titan | `GET /api/v1/monitor/{id}` |
| All monitors | Datadog → Titan | `GET /api/v1/monitor` |

All operations are authenticated using API key + Application key headers. See [ADR-0002](adr/0002-datadog-export-auth.md) for the auth decision.

## Quick start

```python
from services.exporter.datadog_auth import DatadogAuthConfig
from services.exporter.datadog_export import DatadogExporter

# Load credentials from environment variables
config = DatadogAuthConfig.from_env()
exporter = DatadogExporter(config)
```

Environment variables required:

```bash
export DATADOG_API_KEY=your-api-key
export DATADOG_APP_KEY=your-app-key
# Optional: override the default site (datadoghq.com)
export DATADOG_SITE=datadoghq.eu
```

## Submitting metrics

Use `export_metrics` to push time-series data to Datadog. Each metric follows the [Datadog v2 series schema](https://docs.datadoghq.com/api/latest/metrics/#submit-metrics).

```python
import time

metrics = [
    {
        "metric": "titan.export.count",
        "type": 1,  # 1 = count
        "points": [{"timestamp": int(time.time()), "value": 1.0}],
        "tags": ["env:production", "service:titan", "tenant:acme"],
    },
    {
        "metric": "titan.export.latency_ms",
        "type": 3,  # 3 = gauge
        "points": [{"timestamp": int(time.time()), "value": 142.5}],
        "tags": ["env:production", "service:titan"],
    },
]

result = exporter.export_metrics(metrics)

if result.success:
    print(f"Metrics accepted (HTTP {result.status_code})")
else:
    print(f"Submission failed: {result.errors}")
```

### Metric types

| Type value | Name | When to use |
|------------|------|-------------|
| `0` | Unspecified | Avoid — Datadog will infer |
| `1` | Count | Monotonically increasing counters (e.g. job completions) |
| `2` | Rate | Per-second rates |
| `3` | Gauge | Point-in-time values (e.g. queue depth, latency) |

## Exporting a dashboard

Retrieve a Datadog dashboard definition by its ID.

```python
result = exporter.export_dashboard("abc-123-xyz")

if result.success:
    dashboard = result.payload
    print(f"Dashboard title: {dashboard['title']}")
    print(f"Widget count: {len(dashboard.get('widgets', []))}")
else:
    print(f"Dashboard export failed (HTTP {result.status_code})")
```

The dashboard ID is the alphanumeric string in the Datadog URL:
`https://app.datadoghq.com/dashboard/abc-123-xyz/my-dashboard`

## Exporting a monitor

Retrieve a single monitor by its numeric ID.

```python
result = exporter.export_monitor(12345)

if result.success:
    monitor = result.payload
    print(f"Monitor name: {monitor['name']}")
    print(f"Status: {monitor['overall_state']}")
    print(f"Query: {monitor['query']}")
```

### Exporting all monitors for a service

Use `export_all_monitors` with tag filters to scope the export to a specific service or environment.

```python
result = exporter.export_all_monitors(tags=["service:titan", "env:production"])

monitors = result.payload.get("monitors", [])
print(f"Found {len(monitors)} monitors")

for m in monitors:
    print(f"  [{m['id']}] {m['name']} — {m['overall_state']}")
```

Omit `tags` to retrieve all monitors your App key has access to.

## Error handling

`DatadogExporter` raises structured exceptions on failure:

| Exception | Cause |
|-----------|-------|
| `AuthenticationError` | HTTP 401 or 403 — bad or missing credentials |
| `ExportError` | Network failure or 5xx after all retries exhausted |
| `AuthConfigError` | Missing `DATADOG_API_KEY` or `DATADOG_APP_KEY` at startup |

```python
from services.exporter.datadog_export import AuthenticationError, ExportError
from services.exporter.datadog_auth import AuthConfigError

try:
    config = DatadogAuthConfig.from_env()
    exporter = DatadogExporter(config)
    result = exporter.export_monitor(12345)
except AuthConfigError as e:
    print(f"Bad config — check environment variables: {e}")
except AuthenticationError as e:
    print(f"Datadog rejected credentials: {e}")
except ExportError as e:
    print(f"Export failed after retries: {e}")
```

## Retry behaviour

The exporter automatically retries on transient failures:

- **Retried**: `RequestException` (network errors), HTTP 5xx, HTTP 429
- **Not retried**: HTTP 401, 403 (raises `AuthenticationError` immediately)
- **Max attempts**: 3
- **Backoff**: exponential — `1.5^attempt` seconds (i.e. 1 s, 1.5 s, 2.25 s)

For budget-aware retry control at the worker level, see [ADR-0001](adr/0001-retry-budget-policy.md).

## Related

- [ADR-0002: Datadog export auth](adr/0002-datadog-export-auth.md)
- [Architecture overview](architecture.md)

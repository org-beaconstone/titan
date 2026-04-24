# Datadog authentication examples

This guide walks through setting up Datadog credentials for the Titan exporter in local development, CI, and production environments.

## Prerequisites

You will need two Datadog credentials:

- **API key** (`DATADOG_API_KEY`) — identifies your Datadog organisation. Found in Datadog → Organisation Settings → API Keys.
- **Application key** (`DATADOG_APP_KEY`) — grants access to read/write resources. Found in Datadog → Organisation Settings → Application Keys.

Optionally:

- **Site** (`DATADOG_SITE`) — defaults to `datadoghq.com`. Set to `datadoghq.eu` for EU-region accounts, or `us3.datadoghq.com` / `us5.datadoghq.com` for other regions.

---

## Local development

Export the variables in your shell before running any Titan service:

```bash
export DATADOG_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export DATADOG_APP_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Optional — only needed for non-US1 accounts
export DATADOG_SITE=datadoghq.com
```

Or add them to a `.env` file (never commit this file):

```bash
# .env  — listed in .gitignore
DATADOG_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DATADOG_APP_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DATADOG_SITE=datadoghq.com
```

Load with your preferred tool (e.g. `direnv`, `python-dotenv`, or `source .env`).

### Verify credentials are loaded

```python
from services.exporter.datadog_auth import DatadogAuthConfig, AuthConfigError

try:
    config = DatadogAuthConfig.from_env()
    print(f"Auth OK — site: {config.site}")
    print(f"API key prefix: {config.api_key[:6]}…")
except AuthConfigError as e:
    print(f"Auth config missing: {e}")
```

Expected output:
```
Auth OK — site: datadoghq.com
API key prefix: xxxxxx…
```

---

## CI (GitHub Actions)

Store credentials as repository secrets and inject them into the job environment:

```yaml
# .github/workflows/ci.yml
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      DATADOG_API_KEY: ${{ secrets.DATADOG_API_KEY }}
      DATADOG_APP_KEY: ${{ secrets.DATADOG_APP_KEY }}
      DATADOG_SITE: datadoghq.com
    steps:
      - uses: actions/checkout@v4
      - name: Run exporter tests
        run: pytest services/exporter/
```

Add secrets at: **Repository → Settings → Secrets and variables → Actions → New repository secret**.

---

## Production (container environment)

Inject credentials at the infrastructure layer — never bake them into images or config files.

Example Docker run:

```bash
docker run \
  -e DATADOG_API_KEY="$DATADOG_API_KEY" \
  -e DATADOG_APP_KEY="$DATADOG_APP_KEY" \
  -e DATADOG_SITE="datadoghq.com" \
  titan-exporter:latest
```

Example Kubernetes secret + deployment:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: datadog-credentials
type: Opaque
stringData:
  api-key: <your-api-key>
  app-key: <your-app-key>
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: titan-exporter
spec:
  template:
    spec:
      containers:
        - name: exporter
          image: titan-exporter:latest
          env:
            - name: DATADOG_API_KEY
              valueFrom:
                secretKeyRef:
                  name: datadog-credentials
                  key: api-key
            - name: DATADOG_APP_KEY
              valueFrom:
                secretKeyRef:
                  name: datadog-credentials
                  key: app-key
            - name: DATADOG_SITE
              value: datadoghq.com
```

---

## Using the exporter

### Instantiate the exporter

```python
from services.exporter.datadog_auth import DatadogAuthConfig
from services.exporter.datadog_export import DatadogExporter

config = DatadogAuthConfig.from_env()
exporter = DatadogExporter(config)
```

### Export a monitor by ID

```python
result = exporter.export_monitor(12345)

if result.success:
    print(f"Monitor: {result.payload['name']}")
    print(f"State:   {result.payload['overall_state']}")
    print(f"Query:   {result.payload['query']}")
else:
    print(f"Failed (HTTP {result.status_code})")
```

### Export all monitors for a service

```python
result = exporter.export_all_monitors(tags=["service:titan", "env:production"])
monitors = result.payload.get("monitors", [])

for m in monitors:
    print(f"[{m['id']}] {m['name']} — {m['overall_state']}")
```

### Export a dashboard

```python
# Dashboard ID is the alphanumeric string in the Datadog URL:
# https://app.datadoghq.com/dashboard/abc-123-xyz/my-dashboard
result = exporter.export_dashboard("abc-123-xyz")

if result.success:
    print(f"Title: {result.payload['title']}")
    print(f"Widgets: {len(result.payload.get('widgets', []))}")
```

### Submit metrics

```python
import time

result = exporter.export_metrics([
    {
        "metric": "titan.export.count",
        "type": 1,  # count
        "points": [{"timestamp": int(time.time()), "value": 1.0}],
        "tags": ["env:production", "service:titan"],
    }
])

print("Accepted" if result.success else f"Failed: {result.status_code}")
```

---

## Troubleshooting

### `AuthConfigError: DATADOG_API_KEY is not set`

The environment variable is missing or empty. Run `echo $DATADOG_API_KEY` to check. If blank, re-export it in your shell or confirm your `.env` file is being loaded.

### HTTP 403 — valid key, wrong permissions

Your Application key may not have the required scopes. In Datadog → Organisation Settings → Application Keys, confirm the key has at minimum:
- `monitors_read` — to export monitors
- `dashboards_read` — to export dashboards
- `metrics_write` — to submit metric series

### HTTP 401 — invalid key

The key value is incorrect or has been revoked. Generate a new key in Datadog and update the environment variable.

### Wrong site — `404 Not Found` on all requests

If your Datadog account is on the EU or other regional site, set `DATADOG_SITE` accordingly:

| Region | `DATADOG_SITE` value |
|--------|----------------------|
| US1 (default) | `datadoghq.com` |
| EU | `datadoghq.eu` |
| US3 | `us3.datadoghq.com` |
| US5 | `us5.datadoghq.com` |

### Rate limiting (`ExportError` after retries)

If you are exporting many monitors in a short period, you may hit Datadog's rate limit (varies by plan). The exporter retries up to 3 times with exponential backoff. If errors persist, add a delay between export calls or consider batching exports with a scheduled job. See [ADR-0003](adr/0003-datadog-export-strategy.md) for the longer-term caching strategy.

---

## Related

- [Datadog export reference](datadog-export.md)
- [ADR-0002: Datadog export auth decision](adr/0002-datadog-export-auth.md)
- [ADR-0003: Datadog export strategy](adr/0003-datadog-export-strategy.md)

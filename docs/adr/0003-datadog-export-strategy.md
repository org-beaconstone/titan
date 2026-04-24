# ADR-0003: Datadog resource export strategy

**Status:** Accepted  
**Date:** 2026-04-24  
**Authors:** lsmith-beacon, lestrada-1a  
**Supersedes:** —  
**Related:** [ADR-0002](0002-datadog-export-auth.md), [PR #4](https://github.com/org-beaconstone/titan/pull/4), [PR #14](https://github.com/org-beaconstone/titan/pull/14), [PR #18](https://github.com/org-beaconstone/titan/pull/18) (closed spike), [Issue #2](https://github.com/org-beaconstone/titan/issues/2)

---

## Context

Titan exports Datadog resources (monitors, dashboards, metric series) as part of its background job pipeline. The initial implementation used a **pull-on-demand** model: each job request calls the Datadog API directly via `DatadogExporter` (PR #4, PR #14).

Under low traffic this works well. However, load testing ahead of the Titan launch revealed that high job volume causes `export_all_monitors` to exhaust Datadog's API rate limit (~429 responses at ~200 req/min). A spike was conducted to evaluate bulk scheduled sync as an alternative (PR #18), but it was closed without merging due to missing cache infrastructure.

We need to formalise the chosen approach and establish a clear next step.

## Approaches considered

### Approach A: Pull-on-demand (current)

Each job request calls the Datadog API directly at the moment the data is needed.

**How it works:**  
`DatadogExporter.export_monitor(id)` or `export_all_monitors(tags)` is called inline within the job handler. Results are used immediately and discarded.

**Pros:**
- Simple — no cache layer, no scheduled infrastructure
- Always returns fresh data
- Already implemented and in production

**Cons:**
- One Datadog API call per job request — does not scale under high job volume
- Vulnerable to Datadog API rate limits (observed 429s at ~200 req/min in load test)
- Retry amplification: 3 retries × N concurrent jobs = up to 3N API calls in a burst

---

### Approach B: Bulk scheduled sync (spiked — deferred)

A cron job (`BulkSyncExporter.sync_all`) pre-fetches all monitors on a schedule (e.g. nightly) and writes results to a shared cache. Jobs read from cache instead of calling Datadog directly.

**How it works:**  
`BulkSyncExporter` runs on a schedule, calls `GET /api/v1/monitor` once, and persists results to Redis or a DB table. Job handlers read from the cache — zero Datadog API calls at job time.

**Pros:**
- Minimises Datadog API calls — N jobs share 1 scheduled fetch
- Immune to per-request rate limiting
- Decouples job latency from Datadog API availability

**Cons:**
- Requires a persistent cache layer (Redis or DB) not yet in the platform
- Introduces staleness risk — monitor changes are not visible until the next sync run
- New operational failure mode: silent staleness if cron misses a run; needs monitoring
- Significantly higher complexity for the current traffic level

**Decision:** Deferred. The cache infrastructure dependency makes this out of scope for the current milestone. Revisit when Titan has a shared cache layer. See PR #18 for the spike.

---

### Approach C: Webhook / event-driven

Datadog pushes change events to a Titan webhook endpoint. Titan updates its local copy of monitors/dashboards incrementally on each event.

**How it works:**  
Register a webhook in Datadog → Integrations → Webhooks. Titan exposes a `POST /internal/datadog/webhook` endpoint that receives events and updates the local store.

**Pros:**
- Real-time updates — no polling or staleness
- Very low Datadog API call volume (events are push, not pull)

**Cons:**
- Requires a publicly reachable endpoint — adds infrastructure and security surface
- Datadog webhook payloads are event notifications, not full resource definitions; a follow-up `GET` is still needed to fetch the updated resource
- Complex failure handling: missed events, replay, ordering guarantees
- Overkill for the current use case (monitor export for reporting, not real-time alerting)

**Decision:** Not suitable for the current use case. May be worth revisiting if Titan evolves into a real-time monitoring product.

---

## Decision

**Remain on pull-on-demand (Approach A) with TTL-based in-memory caching added to `DatadogExporter`.**

This is the minimum viable fix for the rate limit problem at current traffic levels, with no new infrastructure dependencies.

### What changes

Add an optional TTL cache inside `DatadogExporter`:

- `export_monitor(id)` and `export_all_monitors(tags)` check an in-process dict cache before calling Datadog
- Cache entries expire after a configurable TTL (default: 300 seconds / 5 minutes)
- On a 429 response, return the cached result if available rather than raising `ExportError`
- Cache is per-process (not shared across workers) — acceptable at current scale

### What does not change

- `export_metrics` is write-only and is never cached
- `export_dashboard` is called infrequently enough that caching is optional (add if needed)
- Auth mechanism (ADR-0002) is unchanged

## Next step

Implement TTL-based in-memory caching in `DatadogExporter` as a follow-on PR (`feature/datadog-export-cache`). Acceptance criteria:

1. `export_monitor` and `export_all_monitors` serve results from cache if a valid entry exists
2. Cache TTL is configurable via `DatadogExporter.__init__` (default 300 s)
3. A 429 response falls back to a cached result if available; raises `ExportError` only if no cache entry exists
4. Cache is cleared / bypassed when `force_refresh=True` is passed
5. `docs/datadog-export.md` updated with a "Caching" section

## Consequences

**Positive:**
- Eliminates 429 errors for repeated exports of the same monitors within the TTL window
- No new infrastructure — cache lives in process memory
- Graceful degradation on 429: stale data is better than an error for reporting jobs

**Negative / mitigations:**
- In-process cache is not shared across worker processes — each worker warms its own cache independently
  - *Mitigation*: Acceptable at current scale; revisit with Approach B (bulk sync) when a shared cache is available
- Stale data within TTL window — monitor changes may not be reflected for up to 5 minutes
  - *Mitigation*: TTL is configurable; callers can pass `force_refresh=True` when freshness is critical

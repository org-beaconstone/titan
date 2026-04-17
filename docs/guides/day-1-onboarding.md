# Day 1 onboarding guide

Welcome to Titan. Start with these documents in order:

1. `README.md` — overview of repository structure and key operational themes
2. `docs/architecture.md` — high-level service boundaries and risk areas
3. `docs/adr/0001-retry-budget-policy.md` — why retry behavior is bounded
4. `docs/adr/0002-datadog-export-auth.md` — exporter auth decisions
5. `docs/releases/v2.4.1.md` — most recent release context
6. `docs/incidents/timeout-retrospective.md` — recent operational lessons

## Areas to understand early
- timeout handling in `services/api/timeouts.py`
- retry logic in `services/api/retries.py`
- worker recovery in `services/worker/retry_backfill.py`
- Datadog export and auth flows in `services/exporter/`

## First-week expectations
New contributors should be able to explain how timeout classification, retry budgets, and export reliability affect launch readiness for Beaconstone tenants.

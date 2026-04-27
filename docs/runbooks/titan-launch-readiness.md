# Titan launch readiness runbook

This runbook covers the operational checklist and no-go conditions for the Titan Jul 28 GA date.

## Current status (as of Apr 21)

| Area | Status |
|------|--------|
| QA regression pass rate | **92%** (target: ≥95% for GA go) |
| DW-881 data warehouse migration | **AT RISK** — 2-day timeline slip (see TPTL-6) |
| Personalization engine | **Deferred to Q4** (TITAN-280) |
| Datadog export pipeline | ✅ DW-881 clean — `_DW_DEPENDENCY = False` |
| Retry budget controls | ✅ Implemented (ADR-0001) |
| Datadog auth | ✅ Implemented (ADR-0002) |

Primary warroom contacts: **Liam Estrada**, **Aoife Burke**  
Warroom channel: `#titan-warroom`

---

## GA go / no-go criteria

### Go conditions (all must be true)

- [ ] QA regression pass rate ≥ 95%
- [ ] Zero open BLOCKER-severity Jira issues in the `TPTL` project
- [ ] DW-881 migration ready-for-prod with ≥ 2 days buffer before Jul 28
- [ ] All no-go triggers below confirmed clear
- [ ] Datadog export pipeline validated under load (no 429s in 30-min soak)
- [ ] Retry budget not exhausted in any 1-hour window during soak

### No-go triggers (any one blocks GA)

| Trigger | Owner | Tracking |
|---------|-------|----------|
| Any new dependency on DW-881 in core collaboration flows | Liam Estrada | TPTL-6 |
| QA regression pass rate drops below 90% | Aoife Burke | — |
| New BLOCKER Jira issue opened in `TPTL` | On-call | — |
| Datadog export pipeline producing `GABlockerError` at startup | Exporter team | TPTL-6 |

---

## DW-881 dependency checklist

Before merging any PR that touches `services/`, `services/exporter/`, or `services/worker/`:

1. **Search for `dw_dependency=True`** in changed files. If found, do not merge — trigger a no-go review.
2. **Check `_DW_DEPENDENCY` flag** in `services/exporter/datadog_export.py`. Must be `False` for GA.
3. **Check `Job.dw_dependency`** — no `ExportJob` or `ReportJob` should set this to `True` in the queue path.
4. **Run the DW-881 dependency smoke test** (CI step `check-dw-dependency`) — fails if any of the above are violated.

If a DW-881 dependency is detected:
1. Immediately flag in `#titan-warroom`
2. Ping Liam Estrada and Aoife Burke
3. Do not deploy until the dependency is removed or explicitly approved as an exception

---

## QA gate

Current regression pass rate: **92%**

| Threshold | Action |
|-----------|--------|
| ≥ 95% | GA go condition met for QA |
| 90–94% | Amber — warroom review required before GA call |
| < 90% | No-go — block GA until rate recovers |

QA results are updated daily in `#titan-qa-status`. The authoritative source is the QA dashboard in Datadog (dashboard ID: `titan-qa-overview`).

---

## Datadog export pipeline — GA readiness notes

The Titan exporter is confirmed free of DW-881 dependencies:

- `services/exporter/datadog_export.py` — `_DW_DEPENDENCY = False`; `GABlockerError` raised at startup if this ever changes
- `services/worker/jobs.py` — `JobQueue.enqueue()` calls `check_ga_readiness()` which rejects any job with `dw_dependency=True`
- `services/api/error_handling.py` — `GABlockerError` classified as `ErrorClass.GA_BLOCKER`, logged at CRITICAL, warroom alerted

Load test results (Apr 21 soak, 200 req/min, 30 min):
- 429 rate: **0%** after TTL cache enabled (PR #21)
- `ExportError` rate: **0%**
- Cache hit rate: **~87%** for `export_all_monitors`

---

## Escalation path

```
On-call engineer
    → #titan-warroom
        → Liam Estrada (DW-881 / export pipeline)
        → Aoife Burke (QA / regression)
            → GA go/no-go call (Liam + Aoife joint decision)
```

Any BLOCKER opened in `TPTL` automatically pages the on-call engineer via the Datadog monitor `titan-blocker-alert`.

---

## Related

- [TPTL-6: DW-881 adds risk to Jul 28 GA](https://beacon-stone.atlassian.net/browse/TPTL-6)
- [ADR-0001: Retry budget policy](adr/0001-retry-budget-policy.md)
- [ADR-0002: Datadog export auth](adr/0002-datadog-export-auth.md)
- [ADR-0003: Datadog export strategy](adr/0003-datadog-export-strategy.md)
- [Datadog export reference](../datadog-export.md)

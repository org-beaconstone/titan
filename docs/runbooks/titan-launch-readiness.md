# Titan launch readiness note

## Purpose
This note is used during Beaconstone launch review to summarize the engineering signals most likely to affect Titan GA confidence.

## Current focus areas
- timeout-related API failures under bursty tenant load
- retry amplification in worker recovery flows
- Datadog export reliability for operational dashboards
- release-note clarity for GTM and support partners

## Recommended launch checks
1. Review recent release notes for v2.4.0 and v2.4.1
2. Confirm timeout retrospective follow-ups are complete
3. Check retry-sensitive code paths for recent behavioral changes
4. Validate export diagnostics for high-priority tenants

## Current status
Launch readiness is improving, but timeout and retry-related changes should be reviewed together when summarizing what shipped or assessing risk.

- Refreshed at 2026-04-17 15:09 AEST to validate demo visibility.

## TPTL-35 rollback-readiness review

For the final Titan GA wave, the launch manager needs a compact recommendation that combines account-sync timeout rate, provisioning queue depth, and retry skip rate. The `services/worker/rollback_readiness.py` helper returns `continue_ga_wave` only when all three signals are within the launch guardrails; otherwise it returns `review_required` with the contributing evidence.

This demo-only change is tracked in `TPTL-35` and requires SRE review before it is used to inform a launch decision.

## Handoff checklist

Before handing launch readiness to the next reviewer, capture the latest release note reviewed, any open timeout follow-up, and the Datadog export signal that was used to confirm operational confidence.

## Retry-window validation

For the Jul 16 sprint, engineering should compare the worker backfill elapsed time against onboarding-dashboard timestamps before treating a dry run as healthy. A small gap can be acceptable when the queue is draining normally, but the launch review needs evidence that the gap is not masking delayed retries for priority Beaconstone tenants.

Use the backfill run summary, worker logs, and dashboard refresh time together. Do not use the dashboard timestamp by itself as proof that replay has completed.

## Onboarding panel validation

Before launch sign-off, support and engineering should run one retry-path check where the provisioning backend and onboarding status panel are compared after the retry completes. If the panel still shows the old state after refresh, the launch review should decide whether to block, fix, or document the behavior for support.

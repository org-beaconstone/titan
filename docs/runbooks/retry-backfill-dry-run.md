# Retry backfill dry-run runbook

## Why this exists
Retry backfills can amplify queue pressure if a replay window is started before tenant scope, retry budget, and operator approval are clear.

## Dry-run checklist
- Generate a dry-run plan before mutating queue state
- Confirm the number of jobs to replay per tenant stays within retry budget
- Escalate high-priority tenants or skipped jobs for operator approval
- Attach the dry-run summary to the launch-readiness thread before execution

## Merge criteria
- Unit coverage for budget-capped replay planning
- Runbook reviewed by SRE
- No production replay starts from this code path yet

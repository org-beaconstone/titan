# Customer onboarding readiness checklist

## Purpose
Support and launch reviewers use this checklist before advising broader Titan onboarding for Beaconstone customers.

## Checks
- Confirm onboarding blocker status in TPTL-3
- Confirm support readiness question in TPTL-32
- Confirm implementation signals in PR #39
- Confirm no unlinked pull requests change the customer answer
- Confirm the support FAQ is current
- For a successful provisioning retry, capture the backend and panel evidence below before treating the onboarding status as current (TPTI-267, TPTI-266)

## Retry-path evidence for support handoff
Record one controlled retry without customer secrets or live personal data. Do not infer panel freshness from the backend state alone.

| Field | Evidence to record |
| --- | --- |
| Tenant/test case | Non-sensitive test identifier and retry scenario |
| Retry completion | Timestamp, authoritative backend provisioning state, and worker log or run-summary reference |
| Panel observation | Panel state and timestamp immediately after retry, after normal refresh, and after page reopen |
| Discrepancy | Whether panel and backend disagreed, and when they converged, if known |
| Validation owner | Engineer or SRE who checked the evidence, with review date |
| Support decision | Block onboarding, fix the panel behavior, or document a support limitation; name the decision owner and link the approved support note |

TPTI-266 remains the blocked panel-freshness issue. TPTI-267 tracks collecting this evidence and handing it to support. Do not treat the checklist or this documentation change as a fix, an SRE sign-off, or a customer-ready decision.

## Current result
PR #39 still needs PM and support review. The retry-path evidence and support decision for TPTI-266 and TPTL-32 also remain open; do not advise broader onboarding until the relevant owners confirm readiness.

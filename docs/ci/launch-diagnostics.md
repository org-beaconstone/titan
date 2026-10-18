# Launch diagnostics: review and handoff

## What this change covers
The launch signal helpers count `ready`, `watch`, and `blocked` observations and flag a blocking signal. The worker queue summary adds a freshness guard to the existing depth and draining checks. This is review context for [TPTI-268](https://beacon-stone.atlassian.net/browse/TPTI-268), [TPTI-259](https://beacon-stone.atlassian.net/browse/TPTI-259), and the [TPTL-34](https://beacon-stone.atlassian.net/browse/TPTL-34) handoff, not an assertion of GA sign-off.

## Reviewer checks
- A `blocked` diagnostic pauses the launch review; `watch` requires owner follow-up, and `ready` is not sufficient when supporting evidence is stale.
- Pass the age of the queue observation, measured in seconds from the same trusted clock as the observation timestamp, to `queue_handoff_summary`. The default maximum age is 300 seconds and can be configured for the handoff. A sample beyond that age, a negative age, or a non-finite age reports `attention_required` even if queue depth is low and the queue is draining.
- The boundary is inclusive: a sample exactly at the maximum age is still current by this guard. Queue depth above 250 or a non-draining queue still reports `attention_required` regardless of age.
- Existing callers that do not supply sample age retain the old depth/draining behavior. A `healthy` result from such a caller is **not** evidence that the queue observation is current. Capture a dated observation before making a customer-readiness statement.

## Before the operational handoff
Record the observation timestamp, queue depth, draining state, age and freshness threshold, and owner. If the sample is stale, refresh the observation and re-evaluate; do not override it with a healthy-looking older reading. Validate replay evidence and support readiness separately. This helper change does not wire new telemetry or close any Jira blockers on its own.

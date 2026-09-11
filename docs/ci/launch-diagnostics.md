# Launch diagnostics notes

## Purpose
Launch diagnostics should help reviewers answer whether Titan is ready for the next July customer-readiness checkpoint.

## Signals to summarize
- Retry budget guardrails
- Worker replay and backfill readiness
- Datadog export health
- Release-note and support handoff coverage

## Reviewer expectations
- Call out `blocked` signals explicitly in PR summaries
- Use `watch` for risks that need follow-up but should not stop merge
- Keep owner names tied to workstreams rather than individual blame

## Next implementation step
Wire these helper functions into the CI summary once the GitHub token used for automation has workflow scope.

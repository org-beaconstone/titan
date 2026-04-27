# Titan

Titan is a revenue operations platform that helps teams manage exports, scheduled reporting, retry-sensitive workflows, and operational diagnostics across tenant-facing services.

This repository contains the application code, architecture notes, ADRs, onboarding guidance, release history, and operational documentation used to support Titan's engineering and customer-facing workflows.

## What Titan contains

Titan is organized around three main areas:

- **API service** — handles customer-facing requests, retry policy, error classification, and timeout-aware behavior
- **Worker jobs** — runs scheduled jobs, backfills, queue polling, and longer-running retry-sensitive tasks
- **Exporter integrations** — contains Datadog-related export logic and authentication examples used by background jobs and admin workflows

## Repository goals

This repository supports the day-to-day engineering workflows required to operate Titan reliably:

- maintaining API retry and timeout behavior
- running worker backfills and scheduled jobs
- managing Datadog exporter integrations
- documenting architectural decisions and operational practices
- supporting release planning, review, and incident follow-up

## Directory overview

```text
.github/workflows/        CI workflows
services/api/             API retry, timeout, and error handling logic
services/worker/          background jobs and retry/backfill utilities
services/exporter/        Datadog auth and export helpers
docs/architecture.md      high-level system structure
docs/guides/              onboarding and task-oriented guides
docs/adr/                 architectural decision records
docs/releases/            release summaries and operational delivery notes
docs/incidents/           operational retrospectives and incident-oriented context
```

## Key documents

Start here if you are new to the codebase:

1. [CONTRIBUTING.md](CONTRIBUTING.md) — development expectations and review workflow
2. [docs/guides/day-1-onboarding.md](docs/guides/day-1-onboarding.md) — suggested reading order for new engineers
3. [docs/architecture.md](docs/architecture.md) — high-level architecture and observability concerns
4. [docs/adr/0001-retry-budget-policy.md](docs/adr/0001-retry-budget-policy.md) — bounded retry rationale
5. [docs/adr/0002-datadog-export-auth.md](docs/adr/0002-datadog-export-auth.md) — exporter auth decision
6. [SECURITY.md](SECURITY.md) — security reporting expectations

## Architecture at a glance

### API service
The API layer contains logic for:
- timeout defaults
- retry classification
- error handling
- review/risk heuristics used in support workflows

Representative files:
- `services/api/retries.py`
- `services/api/timeouts.py`
- `services/api/error_handling.py`
- `services/api/retry_windows.py`
- `services/api/review_queue.py`

### Worker jobs
The worker subsystem focuses on:
- queue polling
- report execution
- failed job replay and recovery
- timeout-sensitive batch processing

Representative files:
- `services/worker/jobs.py`
- `services/worker/retry_backfill.py`

### Exporter integrations
Exporter code models Datadog-related workflows, including:
- authentication headers
- dashboard export
- monitor export
- metric export
- developer-facing authentication examples

Representative files:
- `services/exporter/datadog_auth.py`
- `services/exporter/datadog_export.py`
- [`docs/datadog-auth-examples.md`](docs/datadog-auth-examples.md)
- [`docs/datadog-export.md`](docs/datadog-export.md)

## Operational focus areas

Titan engineering work is organized around a few recurring operational themes:

### Retries and timeout control
Several PRs, issues, and docs focus on retry budgets, timeout tuning, queue polling, and production timeouts. These are meant to support troubleshooting and prioritization workflows.

Relevant examples:
- retry budget improvements
- timeout observability
- retry window controls
- timeout retrospective documentation
- worker retry backfill helper

### CI and diagnostics
CI smoke diagnostics and release diagnostics are represented in both workflow files and historical release changes.

### Datadog export and authentication
The repository includes both implementation code and documentation for Datadog authentication and export scenarios, helping engineers connect runtime behavior with the supporting design and operational guidance.

## Development workflow

Typical contribution flow:

1. branch from `main`
2. make a scoped change
3. open a PR early
4. add comments about risk, blockers, readiness, or rollout concerns
5. merge after review and CI confidence

The repository includes a mix of:
- merged PRs
- open PRs
- blocker comments
- issue links
- release tags
- release history and delivery context

## Review guidance

When reviewing Titan changes, pay particular attention to:
- retry amplification risk
- timeout behavior under load
- exporter auth handling
- CI and diagnostics quality
- production validation requirements for operational changes

Small docs-only PRs may be close to ready quickly, while retry or timeout changes should usually carry stronger evidence and clearer rollout notes.

## Releases

Titan maintains release history for operational review, customer-support context, and release-note workflows:

- [`v2.3.0`](https://github.com/org-beaconstone/titan/releases/tag/v2.3.0)
- [`v2.4.0`](https://github.com/org-beaconstone/titan/releases/tag/v2.4.0)
- [`v2.4.1`](https://github.com/org-beaconstone/titan/releases/tag/v2.4.1)

These releases are backed by dated commits and release notes so teams can compare changes and understand delivery timelines.

## Common engineering tasks

Engineers working in Titan commonly use this repository to:

- review recent release changes
- inspect Datadog exporter behavior
- investigate timeout and retry changes
- validate production-readiness notes before merge
- onboard new engineers through architecture and ADR documentation

## Local setup

For local development and validation:

```bash
python3 -m pytest
```

If you are extending the exporter flows, make sure the following environment variables are set:

```bash
export DATADOG_API_KEY=example-api-key
export DATADOG_APP_KEY=example-app-key
```

## Security

Please do not report security-sensitive issues in public issues or pull requests. Follow the guidance in [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow conventions and review expectations.

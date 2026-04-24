# ADR-0002: Datadog export authentication

**Status:** Accepted  
**Date:** 2026-03-10  
**Authors:** lsmith-beacon  
**Supersedes:** —  
**Related:** [ADR-0001](0001-retry-budget-policy.md), [`services/exporter/datadog_auth.py`](../../services/exporter/datadog_auth.py)

---

## Context

The Titan exporter service makes outbound calls to the Datadog API to submit metrics and retrieve dashboard and monitor definitions. These calls originate from background jobs and admin workflows running inside the Titan worker and API services.

Datadog offers several authentication mechanisms. We needed to choose one that:

1. Works with Datadog's REST API v1 and v2 (both are in use)
2. Does not require browser-based user interaction (calls are service-to-service)
3. Is straightforward to rotate without a code deployment
4. Keeps credentials out of version control and application code
5. Is compatible with the existing Titan environment-variable configuration pattern

## Decision

Use **API key + Application key header-based authentication**.

All Datadog API requests from the exporter include two HTTP headers:

```
DD-API-KEY: <value of DATADOG_API_KEY>
DD-APPLICATION-KEY: <value of DATADOG_APP_KEY>
```

Credentials are loaded exclusively from environment variables (`DATADOG_API_KEY`, `DATADOG_APP_KEY`, and optionally `DATADOG_SITE`) via `DatadogAuthConfig.from_env()`. The config object is validated at startup — if either required key is absent, `AuthConfigError` is raised before any export attempt is made.

The `build_auth_headers()` function is the sole point responsible for constructing the credential headers. No other part of the codebase should embed credentials directly in request construction.

## Alternatives considered

### OAuth 2.0 / OIDC

Datadog supports OAuth for third-party app integrations. This would provide short-lived tokens and scoped consent flows.

**Rejected** because: OAuth is designed for delegated user authorization, not service-to-service background jobs. The token exchange adds operational complexity (token refresh, storage, expiry handling) with no meaningful security benefit in our deployment model, where Titan services already run in a credential-injected environment.

### Hardcoded credentials in application config files

Simple, but introduces serious security risk — any developer with repository read access could extract live credentials.

**Rejected** unconditionally. Credentials must never appear in source control.

### Vault / secrets manager injection

Credentials could be sourced from HashiCorp Vault or a cloud secrets manager rather than plain environment variables.

**Deferred** as future work. The current deployment model uses environment variable injection at the infrastructure layer (CI secrets, container environment), which achieves equivalent isolation without introducing a Vault dependency. If Titan moves to a multi-tenant secrets model, this decision should be revisited.

### Per-request credential generation

Generate short-lived signing tokens for each request (similar to AWS SigV4).

**Not applicable** — Datadog's API does not support request-level signing. API and App keys are long-lived by design.

## Consequences

**Positive:**
- Simple implementation — no token refresh logic or SDK dependency required
- Credentials are rotated by updating an environment variable and restarting the service; no code change needed
- Consistent with how other Titan external integrations handle credentials
- `validate_auth_config()` provides a clear startup-time failure rather than a confusing runtime 401

**Negative / mitigations:**
- API keys and App keys are long-lived; a leaked key grants ongoing access until manually rotated
  - *Mitigation*: keys should be scoped to the minimum required permissions in Datadog's access control; rotation should be triggered immediately on any suspected exposure
- Environment variable injection must be handled correctly by the deployment platform; misconfiguration silently produces empty strings
  - *Mitigation*: `validate_auth_config()` will catch empty-string keys at startup before any request is made

## Compliance note

`DATADOG_API_KEY` and `DATADOG_APP_KEY` must be treated as secrets. They must not appear in:
- log output (the auth module deliberately does not log key values)
- error messages surfaced to end users
- CI job summaries or artifacts

Follow the guidance in [SECURITY.md](../../SECURITY.md) for reporting any suspected credential exposure.

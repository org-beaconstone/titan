"""Readiness helpers for GitHub v1 to v2 connector migration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MigrationSignal:
    tenant: str
    jira_project_key: str
    github_org: str
    linked_work_items: int
    unlinked_pull_requests: int
    support_note_present: bool


def migration_needs_follow_up(signal: MigrationSignal) -> bool:
    """Return whether a tenant needs follow-up before v2 migration."""
    return signal.unlinked_pull_requests > 0 or not signal.support_note_present


def migration_summary(signal: MigrationSignal) -> str:
    status = "needs follow-up" if migration_needs_follow_up(signal) else "ready"
    return f"{signal.tenant} / {signal.jira_project_key} / {signal.github_org}: {status}"

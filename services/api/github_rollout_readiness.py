"""Readiness helpers for GitHub integration rollout."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RolloutSignal:
    tenant: str
    jira_project_key: str
    github_org: str
    linked_work_items: int
    unlinked_pull_requests: int
    support_note_present: bool


def rollout_needs_follow_up(signal: RolloutSignal) -> bool:
    """Return whether a tenant needs follow-up before customer rollout."""
    return signal.unlinked_pull_requests > 0 or not signal.support_note_present


def rollout_summary(signal: RolloutSignal) -> str:
    status = "needs follow-up" if rollout_needs_follow_up(signal) else "ready"
    return f"{signal.tenant} / {signal.jira_project_key} / {signal.github_org}: {status}"

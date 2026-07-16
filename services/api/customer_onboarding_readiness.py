"""Readiness helpers for Titan customer onboarding review."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OnboardingSignal:
    customer: str
    jira_project_key: str
    repository: str
    linked_work_items: int
    unlinked_pull_requests: int
    support_note_present: bool


def onboarding_needs_follow_up(signal: OnboardingSignal) -> bool:
    """Return whether a customer needs follow-up before broader onboarding."""
    return signal.unlinked_pull_requests > 0 or not signal.support_note_present


def onboarding_summary(signal: OnboardingSignal) -> str:
    status = "needs follow-up" if onboarding_needs_follow_up(signal) else "ready"
    return f"{signal.customer} / {signal.jira_project_key} / {signal.repository}: {status}"

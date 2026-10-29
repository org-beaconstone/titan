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
    # None means Jira blocker status has not been checked, not that it is clear.
    unresolved_onboarding_blockers: int | None = None

    def __post_init__(self) -> None:
        if self.linked_work_items < 0 or self.unlinked_pull_requests < 0:
            raise ValueError("work-item and pull-request counts must be non-negative")
        if self.unresolved_onboarding_blockers is not None and self.unresolved_onboarding_blockers < 0:
            raise ValueError("unresolved_onboarding_blockers must be non-negative")


def onboarding_needs_follow_up(signal: OnboardingSignal) -> bool:
    """Require explicit blocker clearance, linked evidence, and a support note."""
    return (
        signal.unresolved_onboarding_blockers != 0
        or signal.linked_work_items <= 0
        or signal.unlinked_pull_requests > 0
        or not signal.support_note_present
    )


def onboarding_summary(signal: OnboardingSignal) -> str:
    status = "needs follow-up" if onboarding_needs_follow_up(signal) else "ready"
    return f"{signal.customer} / {signal.jira_project_key} / {signal.repository}: {status}"

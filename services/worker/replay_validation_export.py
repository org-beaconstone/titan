"""Export replay validation evidence for Titan launch readiness."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayValidationEvidence:
    customer: str
    replay_window: str
    validated_jobs: int
    failed_jobs: int


def export_replay_validation(evidence: ReplayValidationEvidence) -> dict[str, str | int]:
    """Return a compact payload for support and SRE launch handoff."""
    return {
        "customer": evidence.customer,
        "replay_window": evidence.replay_window,
        "validated_jobs": evidence.validated_jobs,
        "failed_jobs": evidence.failed_jobs,
        "status": "ready" if evidence.failed_jobs == 0 else "needs_review",
    }

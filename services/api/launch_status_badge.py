"""Read-only badge model for the Titan launch-status view."""

from __future__ import annotations


def launch_status_badge(*, recommendation: str) -> dict[str, str]:
    """Return display text for the tiger team's launch-status view."""
    if recommendation == "review_required":
        return {
            "state": "needs_review",
            "label": "Launch review required",
            "detail": "Account-sync evidence needs an engineering decision.",
        }
    return {
        "state": "on_track",
        "label": "GA wave on track",
        "detail": "Account-sync evidence is within the launch guardrails.",
    }

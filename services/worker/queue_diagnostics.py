"""Compact account-sync queue diagnostic for Titan launch handoff."""

from __future__ import annotations


def queue_handoff_summary(*, queue_depth: int, draining: bool) -> dict[str, str]:
    """Return the support-facing queue state used in the launch handoff."""
    if queue_depth > 250 or not draining:
        return {
            "state": "attention_required",
            "detail": "Queue needs review before the final GA wave.",
        }
    return {
        "state": "healthy",
        "detail": "Queue is draining within the Titan launch guardrail.",
    }

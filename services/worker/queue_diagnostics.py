"""Compact account-sync queue diagnostic for Titan launch handoff."""

from __future__ import annotations

from math import isfinite


def queue_handoff_summary(
    *,
    queue_depth: int,
    draining: bool,
    sample_age_seconds: float | None = None,
    max_sample_age_seconds: float = 300,
) -> dict[str, str]:
    """Return queue state, guarding against an out-of-date observation.

    Callers without sample age keep the previous queue-depth behavior for
    compatibility. Such a result is not proof that the sample is current.
    """
    if not isfinite(max_sample_age_seconds) or max_sample_age_seconds <= 0:
        raise ValueError("max_sample_age_seconds must be finite and positive")

    if sample_age_seconds is not None and (
        not isfinite(sample_age_seconds)
        or sample_age_seconds < 0
        or sample_age_seconds > max_sample_age_seconds
    ):
        return {
            "state": "attention_required",
            "detail": "Queue observation is stale or invalid; refresh the sample before the GA handoff.",
        }

    if queue_depth > 250 or not draining:
        return {
            "state": "attention_required",
            "detail": "Queue needs review before the final GA wave.",
        }
    return {
        "state": "healthy",
        "detail": "Queue is draining within the Titan launch guardrail.",
    }

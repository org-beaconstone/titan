"""Launch-readiness signal for the Titan account-sync recovery path.

The helper turns retry, timeout, and queue evidence into a concise recommendation
for the GA launch manager. It is intentionally side-effect free so the workflow
can be reviewed in a pull request before changing any production automation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RollbackReadinessSignal:
    """Evidence-backed recommendation produced during a launch review."""

    recommendation: str
    reasons: tuple[str, ...]


def assess_rollback_readiness(
    *,
    timeout_rate: float,
    queue_depth: int,
    retry_skip_rate: float,
) -> RollbackReadinessSignal:
    """Recommend whether Titan can continue the GA wave.

    Thresholds mirror the launch runbook: a timeout rate above 3%, queue depth
    above 250, or a retry skip rate above 10% requires a launch-manager review.
    """
    reasons: list[str] = []
    if timeout_rate > 0.03:
        reasons.append(f"account-sync timeout rate is {timeout_rate:.1%}, above 3%")
    if queue_depth > 250:
        reasons.append(f"provisioning queue depth is {queue_depth}, above 250")
    if retry_skip_rate > 0.10:
        reasons.append(f"retry skip rate is {retry_skip_rate:.1%}, above 10%")

    if reasons:
        return RollbackReadinessSignal("review_required", tuple(reasons))
    return RollbackReadinessSignal(
        "continue_ga_wave",
        ("timeout, queue, and retry signals are within launch guardrails",),
    )

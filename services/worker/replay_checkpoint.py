"""Checkpoint model for worker replay rollout planning.

This is intentionally incomplete: the branch is waiting on production replay
validation before it should be merged.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayCheckpoint:
    tenant_id: str
    latest_processed_job_id: str
    replay_window: str
    validation_state: str = "waiting_for_prod_validation"


def checkpoint_is_merge_ready(checkpoint: ReplayCheckpoint) -> bool:
    """Return whether a replay checkpoint can move past sprint review."""
    return checkpoint.validation_state == "validated"

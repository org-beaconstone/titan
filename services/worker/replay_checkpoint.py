"""Checkpoint model for worker replay validation.

This is intentionally incomplete: the work is waiting on production replay
validation before it should be merged into the Titan launch path.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayCheckpoint:
    customer: str
    latest_processed_job_id: str
    replay_window: str
    validation_state: str = "waiting_for_prod_validation"


def checkpoint_is_merge_ready(checkpoint: ReplayCheckpoint) -> bool:
    """Return whether a replay checkpoint can move past launch review."""
    return checkpoint.validation_state == "validated"

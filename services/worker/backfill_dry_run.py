"""Dry-run planner for Titan worker retry backfills.

The planner keeps replay preparation separate from execution so operators can
review tenant scope, retry budget, and expected queue pressure before starting a
production recovery window.
"""

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class BackfillCandidate:
    tenant_id: str
    failed_jobs: int
    retry_budget: int
    priority: str = "normal"


@dataclass(frozen=True)
class BackfillPlan:
    tenant_id: str
    jobs_to_replay: int
    skipped_jobs: int
    priority: str
    requires_approval: bool


def plan_retry_backfill(candidates: Iterable[BackfillCandidate]) -> list[BackfillPlan]:
    """Build a safe replay plan without mutating queues or job state."""
    plans: list[BackfillPlan] = []
    for candidate in candidates:
        jobs_to_replay = min(candidate.failed_jobs, candidate.retry_budget)
        skipped_jobs = max(candidate.failed_jobs - candidate.retry_budget, 0)
        requires_approval = candidate.priority == "high" or skipped_jobs > 0
        plans.append(
            BackfillPlan(
                tenant_id=candidate.tenant_id,
                jobs_to_replay=jobs_to_replay,
                skipped_jobs=skipped_jobs,
                priority=candidate.priority,
                requires_approval=requires_approval,
            )
        )
    return plans

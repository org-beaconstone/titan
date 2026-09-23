"""
Job queue primitives for the Titan worker service.

Defines the core :class:`Job`, :class:`JobQueue`, and :class:`JobStatus`
types used by the backfill runner, scheduled jobs, and the real-time order
status pipeline.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import List, Optional


class JobStatus(enum.Enum):
    """Lifecycle states for a worker job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobType(enum.Enum):
    """Supported job types processed by the Titan worker."""

    EXPORT = "export"
    REPORT = "report"
    BACKFILL = "backfill"
    ORDER_STATUS_SYNC = "order_status_sync"


@dataclass
class Job:
    """A single unit of work managed by the :class:`JobQueue`.

    Attributes:
        id: Unique identifier for the job.
        type: The :class:`JobType` of work to be performed.
        status: Current :class:`JobStatus` of the job.
        retries: Number of times this job has been re-enqueued.
        failure_reason: Human-readable reason for the last failure, if any.
        dw_dependency: If ``True``, the job is blocked by the TPTL-6 DW-881
                       GA no-go condition and must not be re-enqueued.
        payload: Arbitrary job-specific data.
    """

    type: JobType
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.PENDING
    retries: int = 0
    failure_reason: Optional[str] = None
    dw_dependency: bool = False
    payload: dict = field(default_factory=dict)


class JobQueue:
    """In-memory job queue for the Titan worker service.

    Supports enqueue, dequeue, and failed-job introspection used by the
    :class:`~retry_backfill.BackfillRunner`.
    """

    def __init__(self) -> None:
        self._jobs: List[Job] = []

    def enqueue(self, job: Job) -> None:
        """Add *job* to the queue (or update it if already present).

        Args:
            job: The job to enqueue.
        """
        existing_ids = {j.id for j in self._jobs}
        if job.id in existing_ids:
            for i, j in enumerate(self._jobs):
                if j.id == job.id:
                    self._jobs[i] = job
                    return
        self._jobs.append(job)

    def dequeue(self) -> Optional[Job]:
        """Remove and return the next pending job, or ``None`` if none exists."""
        for job in self._jobs:
            if job.status == JobStatus.PENDING:
                job.status = JobStatus.RUNNING
                return job
        return None

    def failed_jobs(self) -> List[Job]:
        """Return all jobs currently in :attr:`JobStatus.FAILED` state."""
        return [j for j in self._jobs if j.status == JobStatus.FAILED]

    def all_jobs(self) -> List[Job]:
        """Return a snapshot of all jobs in the queue."""
        return list(self._jobs)

"""
Job queue primitives for the Titan worker service.

Jobs are the unit of work dispatched by the API layer and consumed by
background workers. Each job carries a typed payload and tracks its own
lifecycle status.

GA Readiness (TPTL-6 / Jul 28):
    Jobs that touch the data warehouse (DW-881 migration) must set
    ``dw_dependency=True``. The ``check_ga_readiness`` function will
    raise :class:`GABlockerError` for any such job, preventing them from
    entering the queue ahead of the Jul 28 GA date.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any

from services.api.error_handling import GABlockerError

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Lifecycle states for a worker job."""

    PENDING = auto()
    """Job has been enqueued and is awaiting a worker."""

    RUNNING = auto()
    """Job is currently being processed by a worker."""

    COMPLETE = auto()
    """Job finished successfully."""

    FAILED = auto()
    """Job encountered an unrecoverable error."""


class JobType(Enum):
    """Supported job types in the Titan worker."""

    EXPORT = "export"
    """Datadog resource export job."""

    REPORT = "report"
    """Report generation job."""

    BACKFILL = "backfill"
    """Retry backfill job — re-enqueues failed jobs within the retry budget."""


@dataclass
class Job:
    """A unit of work in the Titan job queue.

    Attributes:
        id: Unique job identifier (UUID).
        type: The :class:`JobType` classifying this job.
        payload: Arbitrary job-specific data (e.g. monitor IDs, report params).
        status: Current :class:`JobStatus`.
        created_at: UTC timestamp when the job was created.
        retries: Number of retry attempts made so far.
        failure_reason: Human-readable reason for the last failure, if any.
        dw_dependency: If ``True``, this job reads from or writes to the data
                       warehouse (DW-881 migration path). Jobs with this flag
                       set will be blocked from the queue ahead of the Jul 28
                       GA date — see TPTL-6.
    """

    type: JobType
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    retries: int = 0
    failure_reason: str | None = None
    dw_dependency: bool = False


@dataclass
class ExportJob(Job):
    """A job that exports Datadog resources.

    Payload keys:
        - ``monitor_ids``: list of monitor IDs to export (optional)
        - ``tags``: list of tag filter strings (optional)
        - ``dashboard_id``: single dashboard ID to export (optional)
    """

    def __post_init__(self) -> None:
        self.type = JobType.EXPORT


@dataclass
class ReportJob(Job):
    """A job that generates a Titan report.

    Payload keys:
        - ``report_type``: str — e.g. ``"weekly_summary"``
        - ``tenant_id``: str — the target tenant
        - ``date_range``: dict with ``start`` and ``end`` ISO date strings
    """

    def __post_init__(self) -> None:
        self.type = JobType.REPORT


def check_ga_readiness(job: Job) -> None:
    """Verify a job does not violate the TPTL-6 GA no-go condition.

    If the job has ``dw_dependency=True``, it touches the DW-881 data
    warehouse migration path. This is a no-go trigger ahead of the Jul 28
    GA date and will raise :class:`GABlockerError`.

    Args:
        job: The job to check.

    Raises:
        GABlockerError: If ``job.dw_dependency`` is ``True``.

    Example::

        job = ExportJob(payload={"monitor_ids": [12345]})
        check_ga_readiness(job)  # passes — dw_dependency defaults to False

        risky_job = ReportJob(payload={"report_type": "dw_audit"}, dw_dependency=True)
        check_ga_readiness(risky_job)  # raises GABlockerError
    """
    if job.dw_dependency:
        raise GABlockerError(
            f"Job {job.id} (type={job.type.value}) has dw_dependency=True. "
            "This triggers the TPTL-6 no-go condition — DW-881 dependencies "
            "are blocked from the queue ahead of the Jul 28 GA date. "
            "Contact Liam Estrada or Aoife Burke before re-enabling. "
            "See: https://beacon-stone.atlassian.net/browse/TPTL-6"
        )


class JobQueue:
    """In-process job queue for the Titan worker.

    Applies GA readiness checks at enqueue time so DW-881-dependent jobs
    are rejected before they reach a worker.

    In production this would be backed by a persistent store (e.g. Redis,
    Postgres). This in-memory implementation is used for testing and local
    development.
    """

    def __init__(self) -> None:
        self._queue: list[Job] = []
        self._by_id: dict[str, Job] = {}

    def enqueue(self, job: Job) -> Job:
        """Add a job to the queue.

        Runs :func:`check_ga_readiness` before accepting the job.

        Args:
            job: The job to enqueue.

        Returns:
            The enqueued job (same object, status set to PENDING).

        Raises:
            GABlockerError: If the job has ``dw_dependency=True``.
        """
        check_ga_readiness(job)
        job.status = JobStatus.PENDING
        self._queue.append(job)
        self._by_id[job.id] = job
        logger.info("Enqueued job %s (type=%s)", job.id, job.type.value)
        return job

    def poll(self) -> Job | None:
        """Return the next pending job and mark it RUNNING, or None if empty."""
        for job in self._queue:
            if job.status == JobStatus.PENDING:
                job.status = JobStatus.RUNNING
                logger.info("Polling job %s (type=%s)", job.id, job.type.value)
                return job
        return None

    def mark_complete(self, job_id: str) -> None:
        """Mark a job as COMPLETE."""
        if job := self._by_id.get(job_id):
            job.status = JobStatus.COMPLETE
            logger.info("Job %s complete.", job_id)

    def mark_failed(self, job_id: str, reason: str) -> None:
        """Mark a job as FAILED with a reason string."""
        if job := self._by_id.get(job_id):
            job.status = JobStatus.FAILED
            job.failure_reason = reason
            logger.warning("Job %s failed: %s", job_id, reason)

    def failed_jobs(self) -> list[Job]:
        """Return all jobs currently in FAILED status."""
        return [j for j in self._queue if j.status == JobStatus.FAILED]

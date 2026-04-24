"""
Retry backfill helper for the Titan worker service.

Scans the job queue for failed jobs and re-enqueues them up to the
configured retry budget, applying GA readiness checks before re-enqueue.
See ADR-0001 for the retry budget policy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from services.api.error_handling import GABlockerError, classify_error
from services.api.retries import RetryBudget, RetryPolicy, should_retry
from services.worker.jobs import Job, JobQueue, JobStatus

logger = logging.getLogger(__name__)


@dataclass
class BackfillResult:
    """Summary of a backfill run.

    Attributes:
        attempted: Total number of failed jobs considered.
        re_enqueued: Number of jobs successfully re-enqueued.
        skipped: Number of jobs skipped (budget exhausted, GA blocker, or max retries).
        dry_run: If ``True``, no jobs were actually re-enqueued.
    """

    attempted: int = 0
    re_enqueued: int = 0
    skipped: int = 0
    dry_run: bool = False

    @property
    def skip_rate(self) -> float:
        """Fraction of attempted jobs that were skipped (0.0–1.0)."""
        return self.skipped / self.attempted if self.attempted else 0.0


class BackfillRunner:
    """Scans a :class:`~jobs.JobQueue` for failed jobs and re-enqueues them.

    Re-enqueue is subject to:
    - The configured :class:`~retries.RetryBudget` (windowed attempt cap)
    - Per-job ``max_retries`` threshold
    - GA readiness check (DW-881 dependency guard — see TPTL-6)

    Args:
        queue: The job queue to scan and re-enqueue into.
        policy: Retry policy governing the backfill budget.
        max_retries_per_job: Maximum number of times any single job may be
                             re-enqueued before being permanently skipped.

    Example::

        queue = JobQueue()
        runner = BackfillRunner(queue, max_retries_per_job=3)
        result = runner.run_backfill()
        print(f"Re-enqueued {result.re_enqueued} of {result.attempted} failed jobs.")
    """

    def __init__(
        self,
        queue: JobQueue,
        policy: RetryPolicy | None = None,
        max_retries_per_job: int = 3,
    ) -> None:
        self._queue = queue
        self._budget = RetryBudget(policy or RetryPolicy())
        self._max_retries_per_job = max_retries_per_job

    def run_backfill(self, *, dry_run: bool = False) -> BackfillResult:
        """Scan for failed jobs and re-enqueue eligible ones.

        Args:
            dry_run: If ``True``, evaluate eligibility but do not actually
                     re-enqueue. Useful for auditing without side effects.

        Returns:
            A :class:`BackfillResult` summarising what was (or would be) done.
        """
        result = BackfillResult(dry_run=dry_run)
        failed_jobs = self._queue.failed_jobs()

        logger.info(
            "Backfill run started — %d failed jobs found (dry_run=%s).",
            len(failed_jobs), dry_run,
        )

        for job in failed_jobs:
            result.attempted += 1

            skip_reason = self._skip_reason(job)
            if skip_reason:
                logger.info("Skipping job %s: %s", job.id, skip_reason)
                result.skipped += 1
                continue

            if dry_run:
                logger.info("[dry-run] Would re-enqueue job %s (type=%s, retries=%d).", job.id, job.type.value, job.retries)
                result.re_enqueued += 1
                continue

            try:
                job.retries += 1
                job.status = JobStatus.PENDING
                job.failure_reason = None
                self._queue.enqueue(job)
                self._budget.consume()
                logger.info("Re-enqueued job %s (type=%s, attempt=%d).", job.id, job.type.value, job.retries)
                result.re_enqueued += 1
            except GABlockerError as exc:
                logger.critical("GA blocker prevented re-enqueue of job %s: %s", job.id, exc)
                result.skipped += 1
            except Exception as exc:
                logger.error("Failed to re-enqueue job %s: %s", job.id, exc)
                result.skipped += 1

        logger.info(
            "Backfill run complete — re_enqueued=%d, skipped=%d, attempted=%d.",
            result.re_enqueued, result.skipped, result.attempted,
        )
        return result

    def _skip_reason(self, job: Job) -> str | None:
        """Return a human-readable skip reason, or None if the job is eligible."""
        if job.retries >= self._max_retries_per_job:
            return f"max retries reached ({job.retries}/{self._max_retries_per_job})"

        if job.dw_dependency:
            return "dw_dependency=True — blocked by TPTL-6 GA no-go condition"

        if self._budget.exhausted:
            return "retry budget exhausted for this window"

        return None

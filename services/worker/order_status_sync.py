"""
Order status sync job for the Titan worker service.

Processes :attr:`~jobs.JobType.ORDER_STATUS_SYNC` jobs from the queue,
fetching the latest order state from an upstream source and updating the
:class:`~services.api.order_status.OrderStatusRegistry` so shoppers see
accurate, timely status information.

This worker-side component is the backend half of the real-time order
status feature (SHOP-15). The API-side half lives in
:mod:`services.api.order_status`.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from services.api.order_status import (
    InvalidStatusTransitionError,
    OrderStatusRegistry,
    OrderStatusValue,
)
from services.worker.jobs import Job, JobQueue, JobStatus, JobType

logger = logging.getLogger(__name__)

#: Callable signature for the upstream status fetch hook.
#: Receives an order_id and returns the current :class:`OrderStatusValue`,
#: or ``None`` if the upstream system has no record for the order.
StatusFetcher = Callable[[str], Optional[OrderStatusValue]]


class OrderStatusSyncRunner:
    """Processes ORDER_STATUS_SYNC jobs and keeps the registry up to date.

    Each job's ``payload`` must contain an ``"order_id"`` key identifying
    the order whose status should be refreshed from the upstream source.

    Args:
        queue: The job queue to pull sync jobs from.
        registry: The :class:`~services.api.order_status.OrderStatusRegistry`
                  to update with new status data.
        fetch_upstream: Callable that returns the current
                        :class:`~services.api.order_status.OrderStatusValue`
                        for a given order_id from the upstream order system.
                        Inject a mock during testing.

    Example::

        registry = OrderStatusRegistry()
        registry.register("ORD-1234")

        def fetch(order_id):
            # Replace with real upstream call in production.
            return OrderStatusValue.CONFIRMED

        runner = OrderStatusSyncRunner(queue, registry, fetch_upstream=fetch)
        result = runner.run_sync()
        print(f"Synced {result.synced} orders, skipped {result.skipped}.")
    """

    def __init__(
        self,
        queue: JobQueue,
        registry: OrderStatusRegistry,
        fetch_upstream: StatusFetcher,
    ) -> None:
        self._queue = queue
        self._registry = registry
        self._fetch_upstream = fetch_upstream

    def run_sync(self) -> "SyncResult":
        """Dequeue and process all pending ORDER_STATUS_SYNC jobs.

        Returns:
            A :class:`SyncResult` summarising the outcome.
        """
        result = SyncResult()

        while True:
            job = self._queue.dequeue()
            if job is None:
                break
            if job.type != JobType.ORDER_STATUS_SYNC:
                # Put non-sync jobs back as pending so other workers can pick them up.
                job.status = JobStatus.PENDING
                self._queue.enqueue(job)
                break

            result.attempted += 1
            self._process_job(job, result)

        logger.info(
            "Order status sync complete — synced=%d, skipped=%d, attempted=%d.",
            result.synced,
            result.skipped,
            result.attempted,
        )
        return result

    def _process_job(self, job: Job, result: "SyncResult") -> None:
        order_id = job.payload.get("order_id")
        if not order_id:
            logger.warning("ORDER_STATUS_SYNC job %s missing order_id in payload — skipping.", job.id)
            job.status = JobStatus.FAILED
            job.failure_reason = "missing order_id in payload"
            self._queue.enqueue(job)
            result.skipped += 1
            return

        try:
            upstream_status = self._fetch_upstream(order_id)
        except Exception as exc:
            logger.error("Failed to fetch upstream status for order %s: %s", order_id, exc)
            job.status = JobStatus.FAILED
            job.failure_reason = f"upstream fetch error: {exc}"
            self._queue.enqueue(job)
            result.skipped += 1
            return

        if upstream_status is None:
            logger.info("No upstream status for order %s — skipping.", order_id)
            job.status = JobStatus.SUCCEEDED
            self._queue.enqueue(job)
            result.skipped += 1
            return

        try:
            tracker = self._registry.get_tracker(order_id)
        except KeyError:
            # Auto-register orders we see for the first time.
            tracker = self._registry.register(order_id)
            logger.info("Auto-registered order %s in the status registry.", order_id)

        if tracker.current_status == upstream_status:
            logger.debug("Order %s status unchanged (%s) — no transition needed.", order_id, upstream_status.value)
            job.status = JobStatus.SUCCEEDED
            self._queue.enqueue(job)
            result.skipped += 1
            return

        if tracker.is_terminal:
            logger.info("Order %s is in terminal state %s — skipping upstream update.", order_id, tracker.current_status.value)
            job.status = JobStatus.SUCCEEDED
            self._queue.enqueue(job)
            result.skipped += 1
            return

        try:
            tracker.transition(
                upstream_status,
                note=f"synced by ORDER_STATUS_SYNC job {job.id}",
            )
            job.status = JobStatus.SUCCEEDED
            self._queue.enqueue(job)
            result.synced += 1
            logger.info("Order %s transitioned to %s.", order_id, upstream_status.value)
        except InvalidStatusTransitionError as exc:
            logger.warning("Invalid transition for order %s: %s", order_id, exc)
            job.status = JobStatus.FAILED
            job.failure_reason = str(exc)
            self._queue.enqueue(job)
            result.skipped += 1


class SyncResult:
    """Summary of an :class:`OrderStatusSyncRunner` run.

    Attributes:
        attempted: Total jobs dequeued and processed.
        synced: Orders whose status was successfully updated.
        skipped: Orders skipped due to no change, terminal state, or error.
    """

    def __init__(self) -> None:
        self.attempted: int = 0
        self.synced: int = 0
        self.skipped: int = 0

"""Tests for the ORDER_STATUS_SYNC worker job (SHOP-15)."""

from __future__ import annotations

import pytest

from services.api.order_status import OrderStatusRegistry, OrderStatusValue
from services.worker.jobs import Job, JobQueue, JobStatus, JobType
from services.worker.order_status_sync import OrderStatusSyncRunner, SyncResult


def _make_sync_job(order_id: str) -> Job:
    return Job(type=JobType.ORDER_STATUS_SYNC, payload={"order_id": order_id})


class TestOrderStatusSyncRunner:
    def test_empty_queue_returns_zero_counts(self):
        registry = OrderStatusRegistry()
        queue = JobQueue()
        runner = OrderStatusSyncRunner(queue, registry, fetch_upstream=lambda oid: None)
        result = runner.run_sync()
        assert result.attempted == 0
        assert result.synced == 0
        assert result.skipped == 0

    def test_syncs_status_when_upstream_differs(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-S001")

        queue = JobQueue()
        queue.enqueue(_make_sync_job("ORD-S001"))

        runner = OrderStatusSyncRunner(
            queue, registry, fetch_upstream=lambda oid: OrderStatusValue.CONFIRMED
        )
        result = runner.run_sync()

        assert result.synced == 1
        assert result.skipped == 0
        assert registry.get_tracker("ORD-S001").current_status == OrderStatusValue.CONFIRMED

    def test_skips_when_status_unchanged(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-S002")  # starts at PLACED

        queue = JobQueue()
        queue.enqueue(_make_sync_job("ORD-S002"))

        runner = OrderStatusSyncRunner(
            queue, registry, fetch_upstream=lambda oid: OrderStatusValue.PLACED
        )
        result = runner.run_sync()

        assert result.synced == 0
        assert result.skipped == 1

    def test_skips_terminal_order(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-S003")
        for status in [
            OrderStatusValue.CONFIRMED,
            OrderStatusValue.PROCESSING,
            OrderStatusValue.SHIPPED,
            OrderStatusValue.DELIVERED,
        ]:
            registry.transition("ORD-S003", status)

        queue = JobQueue()
        queue.enqueue(_make_sync_job("ORD-S003"))

        runner = OrderStatusSyncRunner(
            queue, registry, fetch_upstream=lambda oid: OrderStatusValue.CANCELLED
        )
        result = runner.run_sync()

        assert result.skipped == 1
        assert result.synced == 0
        # Status should remain DELIVERED, not CANCELLED.
        assert registry.get_tracker("ORD-S003").current_status == OrderStatusValue.DELIVERED

    def test_auto_registers_unknown_order(self):
        registry = OrderStatusRegistry()
        queue = JobQueue()
        queue.enqueue(_make_sync_job("ORD-S004"))

        runner = OrderStatusSyncRunner(
            queue, registry, fetch_upstream=lambda oid: OrderStatusValue.PLACED
        )
        runner.run_sync()

        # Order should now be in the registry.
        assert "ORD-S004" in registry.registered_orders()

    def test_upstream_returning_none_skips_job(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-S005")

        queue = JobQueue()
        queue.enqueue(_make_sync_job("ORD-S005"))

        runner = OrderStatusSyncRunner(
            queue, registry, fetch_upstream=lambda oid: None
        )
        result = runner.run_sync()

        assert result.skipped == 1
        assert result.synced == 0

    def test_job_without_order_id_marks_failed(self):
        registry = OrderStatusRegistry()
        queue = JobQueue()
        bad_job = Job(type=JobType.ORDER_STATUS_SYNC, payload={})  # no order_id
        queue.enqueue(bad_job)

        runner = OrderStatusSyncRunner(
            queue, registry, fetch_upstream=lambda oid: OrderStatusValue.CONFIRMED
        )
        result = runner.run_sync()

        assert result.skipped == 1
        # The job should be marked as FAILED.
        failed = [j for j in queue.all_jobs() if j.status == JobStatus.FAILED]
        assert len(failed) == 1

    def test_upstream_exception_marks_job_failed(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-S006")

        queue = JobQueue()
        queue.enqueue(_make_sync_job("ORD-S006"))

        def failing_fetch(oid):
            raise RuntimeError("upstream unavailable")

        runner = OrderStatusSyncRunner(queue, registry, fetch_upstream=failing_fetch)
        result = runner.run_sync()

        assert result.skipped == 1
        failed = [j for j in queue.all_jobs() if j.status == JobStatus.FAILED]
        assert len(failed) == 1
        assert "upstream fetch error" in failed[0].failure_reason

    def test_invalid_transition_marks_job_failed(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-S007")  # starts at PLACED

        queue = JobQueue()
        queue.enqueue(_make_sync_job("ORD-S007"))

        # SHIPPED is not a valid transition from PLACED (skips CONFIRMED → PROCESSING).
        runner = OrderStatusSyncRunner(
            queue, registry, fetch_upstream=lambda oid: OrderStatusValue.SHIPPED
        )
        result = runner.run_sync()

        assert result.skipped == 1
        failed = [j for j in queue.all_jobs() if j.status == JobStatus.FAILED]
        assert len(failed) == 1

    def test_processes_multiple_jobs(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-S008")
        registry.register("ORD-S009")

        queue = JobQueue()
        queue.enqueue(_make_sync_job("ORD-S008"))
        queue.enqueue(_make_sync_job("ORD-S009"))

        runner = OrderStatusSyncRunner(
            queue, registry, fetch_upstream=lambda oid: OrderStatusValue.CONFIRMED
        )
        result = runner.run_sync()

        assert result.synced == 2
        assert result.attempted == 2


class TestSyncResult:
    def test_initial_counts_are_zero(self):
        result = SyncResult()
        assert result.attempted == 0
        assert result.synced == 0
        assert result.skipped == 0

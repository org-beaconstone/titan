"""Tests for real-time order status tracking (SHOP-15)."""

from __future__ import annotations

import pytest

from services.api.order_status import (
    InvalidStatusTransitionError,
    OrderStatusRegistry,
    OrderStatusSnapshot,
    OrderStatusTracker,
    OrderStatusValue,
    StatusEvent,
)


# ---------------------------------------------------------------------------
# OrderStatusTracker
# ---------------------------------------------------------------------------


class TestOrderStatusTracker:
    def test_initial_status_defaults_to_placed(self):
        tracker = OrderStatusTracker(order_id="ORD-001")
        assert tracker.current_status == OrderStatusValue.PLACED

    def test_initial_status_can_be_overridden(self):
        tracker = OrderStatusTracker(order_id="ORD-002", initial_status=OrderStatusValue.CONFIRMED)
        assert tracker.current_status == OrderStatusValue.CONFIRMED

    def test_order_id_is_stored(self):
        tracker = OrderStatusTracker(order_id="ORD-003")
        assert tracker.order_id == "ORD-003"

    def test_valid_forward_transition(self):
        tracker = OrderStatusTracker(order_id="ORD-004")
        event = tracker.transition(OrderStatusValue.CONFIRMED)
        assert tracker.current_status == OrderStatusValue.CONFIRMED
        assert isinstance(event, StatusEvent)
        assert event.status == OrderStatusValue.CONFIRMED

    def test_full_happy_path_transitions(self):
        tracker = OrderStatusTracker(order_id="ORD-005")
        for status in [
            OrderStatusValue.CONFIRMED,
            OrderStatusValue.PROCESSING,
            OrderStatusValue.SHIPPED,
            OrderStatusValue.DELIVERED,
        ]:
            tracker.transition(status)
        assert tracker.current_status == OrderStatusValue.DELIVERED

    def test_cancellation_from_placed(self):
        tracker = OrderStatusTracker(order_id="ORD-006")
        tracker.transition(OrderStatusValue.CANCELLED)
        assert tracker.current_status == OrderStatusValue.CANCELLED

    def test_cancellation_from_processing(self):
        tracker = OrderStatusTracker(order_id="ORD-007")
        tracker.transition(OrderStatusValue.CONFIRMED)
        tracker.transition(OrderStatusValue.PROCESSING)
        tracker.transition(OrderStatusValue.CANCELLED)
        assert tracker.current_status == OrderStatusValue.CANCELLED

    def test_invalid_transition_raises(self):
        tracker = OrderStatusTracker(order_id="ORD-008")
        with pytest.raises(InvalidStatusTransitionError):
            tracker.transition(OrderStatusValue.SHIPPED)  # skips steps

    def test_transition_from_terminal_state_raises(self):
        tracker = OrderStatusTracker(order_id="ORD-009")
        tracker.transition(OrderStatusValue.CONFIRMED)
        tracker.transition(OrderStatusValue.PROCESSING)
        tracker.transition(OrderStatusValue.SHIPPED)
        tracker.transition(OrderStatusValue.DELIVERED)
        with pytest.raises(InvalidStatusTransitionError):
            tracker.transition(OrderStatusValue.CANCELLED)

    def test_transition_from_cancelled_raises(self):
        tracker = OrderStatusTracker(order_id="ORD-010")
        tracker.transition(OrderStatusValue.CANCELLED)
        with pytest.raises(InvalidStatusTransitionError):
            tracker.transition(OrderStatusValue.CONFIRMED)

    def test_is_terminal_false_for_in_progress_order(self):
        tracker = OrderStatusTracker(order_id="ORD-011")
        assert not tracker.is_terminal
        tracker.transition(OrderStatusValue.CONFIRMED)
        assert not tracker.is_terminal

    def test_is_terminal_true_after_delivery(self):
        tracker = OrderStatusTracker(order_id="ORD-012")
        for status in [
            OrderStatusValue.CONFIRMED,
            OrderStatusValue.PROCESSING,
            OrderStatusValue.SHIPPED,
            OrderStatusValue.DELIVERED,
        ]:
            tracker.transition(status)
        assert tracker.is_terminal

    def test_is_terminal_true_after_cancellation(self):
        tracker = OrderStatusTracker(order_id="ORD-013")
        tracker.transition(OrderStatusValue.CANCELLED)
        assert tracker.is_terminal

    def test_history_records_all_events(self):
        tracker = OrderStatusTracker(order_id="ORD-014")
        tracker.transition(OrderStatusValue.CONFIRMED)
        tracker.transition(OrderStatusValue.PROCESSING)
        history = tracker.history()
        assert len(history) == 3  # initial PLACED + 2 transitions
        assert history[0].status == OrderStatusValue.PLACED
        assert history[1].status == OrderStatusValue.CONFIRMED
        assert history[2].status == OrderStatusValue.PROCESSING

    def test_history_returns_copy(self):
        tracker = OrderStatusTracker(order_id="ORD-015")
        history = tracker.history()
        history.clear()
        assert len(tracker.history()) == 1  # original untouched

    def test_transition_note_stored(self):
        tracker = OrderStatusTracker(order_id="ORD-016")
        tracker.transition(OrderStatusValue.CONFIRMED, note="payment received")
        assert tracker.history()[-1].note == "payment received"

    def test_transition_note_defaults_to_none(self):
        tracker = OrderStatusTracker(order_id="ORD-017")
        tracker.transition(OrderStatusValue.CONFIRMED)
        assert tracker.history()[-1].note is None


# ---------------------------------------------------------------------------
# StatusEvent
# ---------------------------------------------------------------------------


class TestStatusEvent:
    def test_iso_timestamp_format(self):
        event = StatusEvent(status=OrderStatusValue.PLACED, timestamp=0.0)
        assert event.iso_timestamp == "1970-01-01T00:00:00Z"

    def test_status_stored(self):
        event = StatusEvent(status=OrderStatusValue.SHIPPED)
        assert event.status == OrderStatusValue.SHIPPED


# ---------------------------------------------------------------------------
# OrderStatusSnapshot
# ---------------------------------------------------------------------------


class TestOrderStatusSnapshot:
    def _make_snapshot(self) -> OrderStatusSnapshot:
        tracker = OrderStatusTracker(order_id="ORD-SNAP-001")
        tracker.transition(OrderStatusValue.CONFIRMED)
        return tracker.snapshot()

    def test_snapshot_has_correct_order_id(self):
        snap = self._make_snapshot()
        assert snap.order_id == "ORD-SNAP-001"

    def test_snapshot_current_status(self):
        snap = self._make_snapshot()
        assert snap.current_status == OrderStatusValue.CONFIRMED

    def test_snapshot_history_length(self):
        snap = self._make_snapshot()
        assert len(snap.history) == 2

    def test_snapshot_is_not_terminal(self):
        snap = self._make_snapshot()
        assert not snap.is_terminal

    def test_to_dict_keys(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert set(d.keys()) == {"order_id", "current_status", "is_terminal", "polled_at_iso", "history"}

    def test_to_dict_current_status_is_string(self):
        snap = self._make_snapshot()
        assert snap.to_dict()["current_status"] == "confirmed"

    def test_to_dict_history_entries(self):
        snap = self._make_snapshot()
        history = snap.to_dict()["history"]
        assert len(history) == 2
        assert history[0]["status"] == "placed"
        assert history[1]["status"] == "confirmed"

    def test_to_dict_history_entry_has_required_keys(self):
        snap = self._make_snapshot()
        entry = snap.to_dict()["history"][0]
        assert {"status", "timestamp_iso", "note"} <= set(entry.keys())


# ---------------------------------------------------------------------------
# OrderStatusRegistry
# ---------------------------------------------------------------------------


class TestOrderStatusRegistry:
    def test_register_creates_tracker(self):
        registry = OrderStatusRegistry()
        tracker = registry.register("ORD-R001")
        assert tracker.order_id == "ORD-R001"
        assert tracker.current_status == OrderStatusValue.PLACED

    def test_register_duplicate_raises(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-R002")
        with pytest.raises(ValueError, match="already registered"):
            registry.register("ORD-R002")

    def test_get_tracker_returns_same_instance(self):
        registry = OrderStatusRegistry()
        tracker = registry.register("ORD-R003")
        assert registry.get_tracker("ORD-R003") is tracker

    def test_get_tracker_unknown_order_raises(self):
        registry = OrderStatusRegistry()
        with pytest.raises(KeyError):
            registry.get_tracker("ORD-UNKNOWN")

    def test_transition_updates_status(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-R004")
        registry.transition("ORD-R004", OrderStatusValue.CONFIRMED)
        assert registry.get_tracker("ORD-R004").current_status == OrderStatusValue.CONFIRMED

    def test_transition_unknown_order_raises(self):
        registry = OrderStatusRegistry()
        with pytest.raises(KeyError):
            registry.transition("ORD-UNKNOWN", OrderStatusValue.CONFIRMED)

    def test_get_snapshot_returns_snapshot(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-R005")
        snap = registry.get_snapshot("ORD-R005")
        assert isinstance(snap, OrderStatusSnapshot)
        assert snap.order_id == "ORD-R005"

    def test_get_snapshot_unknown_order_raises(self):
        registry = OrderStatusRegistry()
        with pytest.raises(KeyError):
            registry.get_snapshot("ORD-UNKNOWN")

    def test_registered_orders_lists_all_orders(self):
        registry = OrderStatusRegistry()
        registry.register("ORD-R006")
        registry.register("ORD-R007")
        orders = registry.registered_orders()
        assert "ORD-R006" in orders
        assert "ORD-R007" in orders
        assert len(orders) == 2

    def test_registered_orders_empty_by_default(self):
        registry = OrderStatusRegistry()
        assert registry.registered_orders() == []

    def test_register_with_custom_initial_status(self):
        registry = OrderStatusRegistry()
        tracker = registry.register("ORD-R008", initial_status=OrderStatusValue.CONFIRMED)
        assert tracker.current_status == OrderStatusValue.CONFIRMED

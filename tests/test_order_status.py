"""Tests for services.orders.order_status — real-time order status for shoppers."""

from __future__ import annotations

import pytest

from services.orders.order_status import (
    InvalidStatusTransitionError,
    Order,
    OrderNotFoundError,
    OrderStatus,
    OrderStatusEvent,
    OrderStatusPoller,
    OrderStatusStore,
    StatusUpdate,
)


# ---------------------------------------------------------------------------
# OrderStatus
# ---------------------------------------------------------------------------


class TestOrderStatus:
    def test_terminal_statuses(self):
        assert OrderStatus.DELIVERED.is_terminal is True
        assert OrderStatus.CANCELLED.is_terminal is True

    def test_non_terminal_statuses(self):
        for status in (
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.PROCESSING,
            OrderStatus.SHIPPED,
            OrderStatus.OUT_FOR_DELIVERY,
        ):
            assert status.is_terminal is False

    def test_string_value(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.OUT_FOR_DELIVERY.value == "out_for_delivery"


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


class TestOrder:
    def _make_order(self, **kwargs) -> Order:
        defaults = {"order_id": "ORD-001", "shopper_id": "USR-1"}
        defaults.update(kwargs)
        return Order(**defaults)

    def test_initial_status_defaults_to_pending(self):
        order = self._make_order()
        assert order.status == OrderStatus.PENDING

    def test_history_seeded_on_creation(self):
        order = self._make_order()
        assert len(order.history) == 1
        assert order.history[0].status == OrderStatus.PENDING

    def test_custom_initial_status_recorded_in_history(self):
        order = self._make_order(status=OrderStatus.CONFIRMED)
        assert order.history[0].status == OrderStatus.CONFIRMED

    def test_valid_transition_updates_status(self):
        order = self._make_order()
        order.transition(OrderStatus.CONFIRMED)
        assert order.status == OrderStatus.CONFIRMED

    def test_valid_transition_appends_history(self):
        order = self._make_order()
        order.transition(OrderStatus.CONFIRMED)
        assert len(order.history) == 2
        assert order.history[-1].status == OrderStatus.CONFIRMED

    def test_transition_with_note_stored_in_history(self):
        order = self._make_order()
        order.transition(OrderStatus.CANCELLED, note="customer request")
        assert order.history[-1].note == "customer request"

    def test_invalid_transition_raises(self):
        order = self._make_order()
        with pytest.raises(InvalidStatusTransitionError):
            order.transition(OrderStatus.SHIPPED)  # can't skip steps

    def test_transition_from_terminal_status_raises(self):
        order = self._make_order(status=OrderStatus.DELIVERED)
        with pytest.raises(InvalidStatusTransitionError):
            order.transition(OrderStatus.CANCELLED)

    def test_full_happy_path_lifecycle(self):
        order = self._make_order()
        for status in (
            OrderStatus.CONFIRMED,
            OrderStatus.PROCESSING,
            OrderStatus.SHIPPED,
            OrderStatus.OUT_FOR_DELIVERY,
            OrderStatus.DELIVERED,
        ):
            order.transition(status)
        assert order.status == OrderStatus.DELIVERED
        assert len(order.history) == 6  # initial + 5 transitions

    def test_cancellation_from_processing(self):
        order = self._make_order()
        order.transition(OrderStatus.CONFIRMED)
        order.transition(OrderStatus.PROCESSING)
        order.transition(OrderStatus.CANCELLED, note="out of stock")
        assert order.status == OrderStatus.CANCELLED


# ---------------------------------------------------------------------------
# OrderStatusEvent
# ---------------------------------------------------------------------------


class TestOrderStatusEvent:
    def test_defaults(self):
        event = OrderStatusEvent(status=OrderStatus.PENDING)
        assert event.note == ""
        assert event.timestamp > 0

    def test_custom_note(self):
        event = OrderStatusEvent(status=OrderStatus.SHIPPED, note="dispatched")
        assert event.note == "dispatched"


# ---------------------------------------------------------------------------
# OrderStatusStore
# ---------------------------------------------------------------------------


class TestOrderStatusStore:
    def _make_store(self) -> OrderStatusStore:
        return OrderStatusStore()

    def _make_order(self, order_id: str = "ORD-001", shopper_id: str = "USR-1") -> Order:
        return Order(order_id=order_id, shopper_id=shopper_id)

    def test_add_and_get(self):
        store = self._make_store()
        order = self._make_order()
        store.add(order)
        assert store.get("ORD-001") is order

    def test_get_missing_order_raises(self):
        store = self._make_store()
        with pytest.raises(OrderNotFoundError):
            store.get("DOES-NOT-EXIST")

    def test_update_status_changes_order(self):
        store = self._make_store()
        store.add(self._make_order())
        updated = store.update_status("ORD-001", OrderStatus.CONFIRMED)
        assert updated.status == OrderStatus.CONFIRMED

    def test_update_status_returns_same_object(self):
        store = self._make_store()
        order = self._make_order()
        store.add(order)
        result = store.update_status("ORD-001", OrderStatus.CONFIRMED)
        assert result is order

    def test_update_status_missing_order_raises(self):
        store = self._make_store()
        with pytest.raises(OrderNotFoundError):
            store.update_status("MISSING", OrderStatus.CONFIRMED)

    def test_update_status_invalid_transition_raises(self):
        store = self._make_store()
        store.add(self._make_order())
        with pytest.raises(InvalidStatusTransitionError):
            store.update_status("ORD-001", OrderStatus.DELIVERED)

    def test_orders_for_shopper_filters_correctly(self):
        store = self._make_store()
        store.add(Order(order_id="ORD-001", shopper_id="USR-1"))
        store.add(Order(order_id="ORD-002", shopper_id="USR-2"))
        store.add(Order(order_id="ORD-003", shopper_id="USR-1"))
        result = store.orders_for_shopper("USR-1")
        assert {o.order_id for o in result} == {"ORD-001", "ORD-003"}

    def test_orders_for_unknown_shopper_returns_empty(self):
        store = self._make_store()
        assert store.orders_for_shopper("NOBODY") == []

    def test_all_orders_returns_every_order(self):
        store = self._make_store()
        store.add(Order(order_id="ORD-001", shopper_id="USR-1"))
        store.add(Order(order_id="ORD-002", shopper_id="USR-2"))
        assert len(store.all_orders()) == 2


# ---------------------------------------------------------------------------
# OrderStatusPoller
# ---------------------------------------------------------------------------


class TestOrderStatusPoller:
    def _make_store_with_order(
        self, order_id: str = "ORD-001", shopper_id: str = "USR-1"
    ) -> OrderStatusStore:
        store = OrderStatusStore()
        store.add(Order(order_id=order_id, shopper_id=shopper_id))
        return store

    def test_first_poll_captures_baseline_and_reports_new_orders(self):
        store = self._make_store_with_order()
        poller = OrderStatusPoller(store)
        updates = poller.poll()
        # First poll: new order has no previous status
        assert len(updates) == 1
        assert updates[0].order_id == "ORD-001"
        assert updates[0].previous_status is None
        assert updates[0].current_status == OrderStatus.PENDING

    def test_second_poll_with_no_change_returns_empty(self):
        store = self._make_store_with_order()
        poller = OrderStatusPoller(store)
        poller.poll()  # baseline
        updates = poller.poll()
        assert updates == []

    def test_poll_detects_status_change(self):
        store = self._make_store_with_order()
        poller = OrderStatusPoller(store)
        poller.poll()  # baseline

        store.update_status("ORD-001", OrderStatus.CONFIRMED)
        updates = poller.poll()

        assert len(updates) == 1
        assert updates[0].previous_status == OrderStatus.PENDING
        assert updates[0].current_status == OrderStatus.CONFIRMED

    def test_poll_detects_multiple_changes_across_orders(self):
        store = OrderStatusStore()
        store.add(Order(order_id="ORD-001", shopper_id="USR-1"))
        store.add(Order(order_id="ORD-002", shopper_id="USR-2"))
        poller = OrderStatusPoller(store)
        poller.poll()  # baseline

        store.update_status("ORD-001", OrderStatus.CONFIRMED)
        store.update_status("ORD-002", OrderStatus.CONFIRMED)
        updates = poller.poll()

        assert len(updates) == 2
        order_ids = {u.order_id for u in updates}
        assert order_ids == {"ORD-001", "ORD-002"}

    def test_poll_detects_new_order_added_after_baseline(self):
        store = self._make_store_with_order()
        poller = OrderStatusPoller(store)
        poller.poll()  # baseline for ORD-001

        store.add(Order(order_id="ORD-002", shopper_id="USR-2"))
        updates = poller.poll()

        assert len(updates) == 1
        assert updates[0].order_id == "ORD-002"
        assert updates[0].previous_status is None

    def test_shopper_filter_limits_watched_orders(self):
        store = OrderStatusStore()
        store.add(Order(order_id="ORD-001", shopper_id="USR-1"))
        store.add(Order(order_id="ORD-002", shopper_id="USR-2"))
        poller = OrderStatusPoller(store, shopper_filter=lambda sid: sid == "USR-1")
        poller.poll()  # baseline

        store.update_status("ORD-001", OrderStatus.CONFIRMED)
        store.update_status("ORD-002", OrderStatus.CONFIRMED)
        updates = poller.poll()

        # Only USR-1's order should be in the update
        assert len(updates) == 1
        assert updates[0].order_id == "ORD-001"

    def test_status_update_fields(self):
        store = self._make_store_with_order(order_id="ORD-001", shopper_id="USR-42")
        poller = OrderStatusPoller(store)
        poller.poll()  # baseline

        store.update_status("ORD-001", OrderStatus.CONFIRMED)
        updates = poller.poll()

        update = updates[0]
        assert isinstance(update, StatusUpdate)
        assert update.order_id == "ORD-001"
        assert update.shopper_id == "USR-42"
        assert update.previous_status == OrderStatus.PENDING
        assert update.current_status == OrderStatus.CONFIRMED

    def test_sequential_polls_track_incremental_changes(self):
        store = self._make_store_with_order()
        poller = OrderStatusPoller(store)
        poller.poll()  # baseline

        store.update_status("ORD-001", OrderStatus.CONFIRMED)
        updates = poller.poll()
        assert updates[0].current_status == OrderStatus.CONFIRMED

        store.update_status("ORD-001", OrderStatus.PROCESSING)
        updates = poller.poll()
        assert updates[0].previous_status == OrderStatus.CONFIRMED
        assert updates[0].current_status == OrderStatus.PROCESSING

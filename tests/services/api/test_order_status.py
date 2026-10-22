"""Tests for services.api.order_status — real-time order status for shoppers."""

from __future__ import annotations

import pytest

from services.api.order_status import (
    InvalidStatusTransitionError,
    Order,
    OrderNotFoundError,
    OrderStatus,
    OrderStatusPoller,
    OrderStatusRegistry,
    StatusChangeEvent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry() -> OrderStatusRegistry:
    """Return a registry whose clock returns a fixed monotonically incrementing value."""
    counter = [0.0]

    def _clock() -> float:
        counter[0] += 1.0
        return counter[0]

    return OrderStatusRegistry(clock=_clock)


# ---------------------------------------------------------------------------
# OrderStatusRegistry.register
# ---------------------------------------------------------------------------


class TestOrderStatusRegistryRegister:
    def test_register_creates_pending_order(self):
        registry = _make_registry()
        order = registry.register("ord-1", shopper_id="s-1")
        assert order.id == "ord-1"
        assert order.shopper_id == "s-1"
        assert order.status == OrderStatus.PENDING

    def test_register_records_initial_event(self):
        registry = _make_registry()
        order = registry.register("ord-1", shopper_id="s-1")
        assert len(order.history) == 1
        event = order.history[0]
        assert event.previous_status is None
        assert event.new_status == OrderStatus.PENDING
        assert event.order_id == "ord-1"

    def test_register_returns_retrievable_order(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        assert registry.get("ord-1").id == "ord-1"


# ---------------------------------------------------------------------------
# OrderStatusRegistry.get
# ---------------------------------------------------------------------------


class TestOrderStatusRegistryGet:
    def test_get_raises_for_unknown_order(self):
        registry = _make_registry()
        with pytest.raises(OrderNotFoundError, match="ord-missing"):
            registry.get("ord-missing")


# ---------------------------------------------------------------------------
# OrderStatusRegistry.update_status
# ---------------------------------------------------------------------------


class TestOrderStatusRegistryUpdateStatus:
    def test_valid_transition_updates_status(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.CONFIRMED)
        assert registry.get("ord-1").status == OrderStatus.CONFIRMED

    def test_valid_transition_appends_event(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.CONFIRMED)
        order = registry.get("ord-1")
        assert len(order.history) == 2
        event = order.history[1]
        assert event.previous_status == OrderStatus.PENDING
        assert event.new_status == OrderStatus.CONFIRMED

    def test_transition_note_is_stored(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        event = registry.update_status("ord-1", OrderStatus.SHIPPED, note="1Z999AA1")
        assert event.note == "1Z999AA1"

    def test_same_status_is_noop(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.PENDING)
        assert len(registry.get("ord-1").history) == 1

    def test_forbidden_transition_raises(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.CONFIRMED)
        registry.update_status("ord-1", OrderStatus.SHIPPED)
        registry.update_status("ord-1", OrderStatus.DELIVERED)
        with pytest.raises(InvalidStatusTransitionError):
            registry.update_status("ord-1", OrderStatus.SHIPPED)

    def test_update_from_terminal_delivered_raises(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.CONFIRMED)
        registry.update_status("ord-1", OrderStatus.DELIVERED)
        with pytest.raises(InvalidStatusTransitionError, match="terminal"):
            registry.update_status("ord-1", OrderStatus.PROCESSING)

    def test_update_from_terminal_cancelled_raises(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.CANCELLED)
        with pytest.raises(InvalidStatusTransitionError, match="terminal"):
            registry.update_status("ord-1", OrderStatus.CONFIRMED)

    def test_update_unknown_order_raises(self):
        registry = _make_registry()
        with pytest.raises(OrderNotFoundError):
            registry.update_status("ord-missing", OrderStatus.CONFIRMED)

    def test_full_lifecycle_history(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        for status in (
            OrderStatus.CONFIRMED,
            OrderStatus.PROCESSING,
            OrderStatus.SHIPPED,
            OrderStatus.DELIVERED,
        ):
            registry.update_status("ord-1", status)
        order = registry.get("ord-1")
        statuses = [e.new_status for e in order.history]
        assert statuses == [
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.PROCESSING,
            OrderStatus.SHIPPED,
            OrderStatus.DELIVERED,
        ]


# ---------------------------------------------------------------------------
# Order properties
# ---------------------------------------------------------------------------


class TestOrderProperties:
    def test_is_terminal_false_for_active_order(self):
        registry = _make_registry()
        order = registry.register("ord-1", shopper_id="s-1")
        assert not order.is_terminal

    def test_is_terminal_true_for_delivered(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.CONFIRMED)
        registry.update_status("ord-1", OrderStatus.DELIVERED)
        assert registry.get("ord-1").is_terminal

    def test_is_terminal_true_for_cancelled(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.CANCELLED)
        assert registry.get("ord-1").is_terminal

    def test_last_updated_is_none_before_any_event(self):
        # Construct an Order directly without any history (edge-case guard).
        order = Order(id="x", shopper_id="s")
        assert order.last_updated is None

    def test_last_updated_reflects_most_recent_event(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.CONFIRMED)
        order = registry.get("ord-1")
        assert order.last_updated == order.history[-1].timestamp


# ---------------------------------------------------------------------------
# OrderStatusRegistry.orders_for_shopper
# ---------------------------------------------------------------------------


class TestOrdersForShopper:
    def test_returns_only_shopper_orders(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.register("ord-2", shopper_id="s-2")
        registry.register("ord-3", shopper_id="s-1")
        orders = registry.orders_for_shopper("s-1")
        assert {o.id for o in orders} == {"ord-1", "ord-3"}

    def test_returns_empty_list_for_unknown_shopper(self):
        registry = _make_registry()
        assert registry.orders_for_shopper("s-unknown") == []


# ---------------------------------------------------------------------------
# OrderStatusPoller
# ---------------------------------------------------------------------------


class TestOrderStatusPoller:
    def test_poller_raises_for_unknown_order(self):
        registry = _make_registry()
        with pytest.raises(OrderNotFoundError):
            OrderStatusPoller(registry, "ord-missing", shopper_id="s-1")

    def test_poller_raises_for_wrong_shopper(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        with pytest.raises(PermissionError, match="s-2"):
            OrderStatusPoller(registry, "ord-1", shopper_id="s-2")

    def test_first_poll_returns_initial_event(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        poller = OrderStatusPoller(registry, "ord-1", shopper_id="s-1")
        events = poller.poll()
        assert len(events) == 1
        assert events[0].new_status == OrderStatus.PENDING

    def test_second_poll_returns_only_new_events(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        poller = OrderStatusPoller(registry, "ord-1", shopper_id="s-1")
        poller.poll()  # consume initial PENDING event

        registry.update_status("ord-1", OrderStatus.CONFIRMED)
        registry.update_status("ord-1", OrderStatus.PROCESSING)

        events = poller.poll()
        assert len(events) == 2
        assert events[0].new_status == OrderStatus.CONFIRMED
        assert events[1].new_status == OrderStatus.PROCESSING

    def test_poll_returns_empty_when_no_new_events(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        poller = OrderStatusPoller(registry, "ord-1", shopper_id="s-1")
        poller.poll()  # drain initial event
        assert poller.poll() == []

    def test_has_new_events_true_when_events_pending(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        poller = OrderStatusPoller(registry, "ord-1", shopper_id="s-1")
        assert poller.has_new_events is True

    def test_has_new_events_false_after_full_drain(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        poller = OrderStatusPoller(registry, "ord-1", shopper_id="s-1")
        poller.poll()
        assert poller.has_new_events is False

    def test_current_status_reflects_latest_update(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        poller = OrderStatusPoller(registry, "ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.SHIPPED)
        assert poller.current_status == OrderStatus.SHIPPED

    def test_order_id_property(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        poller = OrderStatusPoller(registry, "ord-1", shopper_id="s-1")
        assert poller.order_id == "ord-1"

    def test_event_stream_yields_all_events_for_terminal_order(self):
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")
        registry.update_status("ord-1", OrderStatus.CONFIRMED)
        registry.update_status("ord-1", OrderStatus.DELIVERED)

        poller = OrderStatusPoller(registry, "ord-1", shopper_id="s-1")
        # poll_interval=0 avoids any real sleeping — the order is already terminal.
        events = list(poller.event_stream(poll_interval=0))
        statuses = [e.new_status for e in events]
        assert statuses == [
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.DELIVERED,
        ]

    def test_event_stream_respects_timeout(self):
        """event_stream must stop when timeout elapses even if order is still active."""
        registry = _make_registry()
        registry.register("ord-1", shopper_id="s-1")

        poller = OrderStatusPoller(registry, "ord-1", shopper_id="s-1")
        events = list(poller.event_stream(poll_interval=0, timeout=0))
        # At minimum the initial PENDING event should have been yielded before
        # the timeout check fires.
        assert any(e.new_status == OrderStatus.PENDING for e in events)

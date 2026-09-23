"""Tests for real-time order status visibility (SHOP-16)."""

from __future__ import annotations

import pytest

from services.orders.order_status import (
    Order,
    OrderStatus,
    OrderStatusPoller,
    OrderStatusStore,
    StatusChangeEvent,
    TERMINAL_STATUSES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_order(order_id: str = "ord-1", shopper_id: str = "s-42", status: OrderStatus = OrderStatus.PENDING) -> Order:
    return Order(id=order_id, shopper_id=shopper_id, status=status)


def store_with(*orders: Order) -> OrderStatusStore:
    store = OrderStatusStore()
    for order in orders:
        store.set(order)
    return store


# ---------------------------------------------------------------------------
# OrderStatus
# ---------------------------------------------------------------------------

class TestOrderStatus:
    def test_all_expected_statuses_exist(self) -> None:
        names = {s.name for s in OrderStatus}
        assert names == {"PENDING", "CONFIRMED", "PREPARING", "READY", "DELIVERED", "CANCELLED"}

    def test_terminal_statuses(self) -> None:
        assert OrderStatus.DELIVERED in TERMINAL_STATUSES
        assert OrderStatus.CANCELLED in TERMINAL_STATUSES
        non_terminal = {s for s in OrderStatus if s not in TERMINAL_STATUSES}
        assert non_terminal == {OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY}


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------

class TestOrder:
    def test_is_terminal_for_delivered(self) -> None:
        order = make_order(status=OrderStatus.DELIVERED)
        assert order.is_terminal is True

    def test_is_terminal_for_cancelled(self) -> None:
        order = make_order(status=OrderStatus.CANCELLED)
        assert order.is_terminal is True

    def test_is_not_terminal_for_active_statuses(self) -> None:
        for status in (OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY):
            order = make_order(status=status)
            assert order.is_terminal is False, f"{status} should not be terminal"

    def test_updated_at_defaults_to_now(self) -> None:
        import time
        before = time.time()
        order = make_order()
        after = time.time()
        assert before <= order.updated_at <= after


# ---------------------------------------------------------------------------
# OrderStatusStore
# ---------------------------------------------------------------------------

class TestOrderStatusStore:
    def test_get_returns_none_for_unknown_order(self) -> None:
        store = OrderStatusStore()
        assert store.get("nonexistent") is None

    def test_set_and_get_round_trip(self) -> None:
        store = OrderStatusStore()
        order = make_order()
        store.set(order)
        assert store.get(order.id) is order

    def test_set_replaces_existing_order(self) -> None:
        store = OrderStatusStore()
        original = make_order(status=OrderStatus.PENDING)
        store.set(original)
        updated = make_order(status=OrderStatus.CONFIRMED)
        store.set(updated)
        assert store.get("ord-1").status == OrderStatus.CONFIRMED

    def test_all_order_ids_returns_snapshot(self) -> None:
        store = store_with(
            make_order("ord-1"),
            make_order("ord-2"),
        )
        ids = store.all_order_ids()
        assert set(ids) == {"ord-1", "ord-2"}

    def test_initial_orders_passed_to_constructor(self) -> None:
        order = make_order("ord-99")
        store = OrderStatusStore(orders={"ord-99": order})
        assert store.get("ord-99") is order


# ---------------------------------------------------------------------------
# OrderStatusPoller — subscription management
# ---------------------------------------------------------------------------

class TestOrderStatusPollerSubscriptions:
    def test_subscribe_registers_callback(self) -> None:
        store = OrderStatusStore()
        poller = OrderStatusPoller(store)
        cb = lambda o: None
        poller.subscribe("ord-1", cb)
        assert poller.subscription_count("ord-1") == 1

    def test_multiple_callbacks_registered_for_same_order(self) -> None:
        store = OrderStatusStore()
        poller = OrderStatusPoller(store)
        poller.subscribe("ord-1", lambda o: None)
        poller.subscribe("ord-1", lambda o: None)
        assert poller.subscription_count("ord-1") == 2

    def test_unsubscribe_removes_callback(self) -> None:
        store = OrderStatusStore()
        poller = OrderStatusPoller(store)
        cb = lambda o: None
        poller.subscribe("ord-1", cb)
        poller.unsubscribe("ord-1", cb)
        assert poller.subscription_count("ord-1") == 0

    def test_unsubscribe_unknown_callback_is_noop(self) -> None:
        store = OrderStatusStore()
        poller = OrderStatusPoller(store)
        poller.unsubscribe("ord-1", lambda o: None)  # should not raise

    def test_subscription_count_zero_for_unknown_order(self) -> None:
        poller = OrderStatusPoller(OrderStatusStore())
        assert poller.subscription_count("ord-does-not-exist") == 0


# ---------------------------------------------------------------------------
# OrderStatusPoller — polling and change detection
# ---------------------------------------------------------------------------

class TestOrderStatusPollerPoll:
    def test_first_poll_seeds_snapshot_without_firing_callbacks(self) -> None:
        store = store_with(make_order(status=OrderStatus.PENDING))
        poller = OrderStatusPoller(store)

        received: list[Order] = []
        poller.subscribe("ord-1", received.append)

        events = poller.poll()

        assert events == []
        assert received == []

    def test_no_change_produces_no_events(self) -> None:
        store = store_with(make_order(status=OrderStatus.PENDING))
        poller = OrderStatusPoller(store)
        poller.poll()  # seed
        events = poller.poll()
        assert events == []

    def test_status_change_produces_event(self) -> None:
        store = store_with(make_order(status=OrderStatus.PENDING))
        poller = OrderStatusPoller(store)
        poller.poll()  # seed

        store.set(make_order(status=OrderStatus.CONFIRMED))
        events = poller.poll()

        assert len(events) == 1
        assert events[0].order.status == OrderStatus.CONFIRMED
        assert events[0].previous_status == OrderStatus.PENDING

    def test_callback_fired_on_status_change(self) -> None:
        store = store_with(make_order(status=OrderStatus.PENDING))
        poller = OrderStatusPoller(store)
        poller.poll()  # seed

        received: list[Order] = []
        poller.subscribe("ord-1", received.append)

        store.set(make_order(status=OrderStatus.CONFIRMED))
        poller.poll()

        assert len(received) == 1
        assert received[0].status == OrderStatus.CONFIRMED

    def test_multiple_callbacks_all_fired(self) -> None:
        store = store_with(make_order(status=OrderStatus.PENDING))
        poller = OrderStatusPoller(store)
        poller.poll()

        log_a: list[Order] = []
        log_b: list[Order] = []
        poller.subscribe("ord-1", log_a.append)
        poller.subscribe("ord-1", log_b.append)

        store.set(make_order(status=OrderStatus.PREPARING))
        poller.poll()

        assert len(log_a) == 1
        assert len(log_b) == 1

    def test_terminal_status_clears_subscriptions(self) -> None:
        store = store_with(make_order(status=OrderStatus.READY))
        poller = OrderStatusPoller(store)
        poller.poll()

        poller.subscribe("ord-1", lambda o: None)

        store.set(make_order(status=OrderStatus.DELIVERED))
        poller.poll()

        assert poller.subscription_count("ord-1") == 0

    def test_no_callbacks_fired_after_terminal_state(self) -> None:
        store = store_with(make_order(status=OrderStatus.READY))
        poller = OrderStatusPoller(store)
        poller.poll()

        received: list[Order] = []
        poller.subscribe("ord-1", received.append)

        store.set(make_order(status=OrderStatus.DELIVERED))
        poller.poll()  # fires callback, clears subscriptions
        received.clear()

        # Simulate a spurious re-delivery (shouldn't happen in practice)
        store.set(make_order(status=OrderStatus.CANCELLED))
        poller.poll()

        assert received == []

    def test_multiple_orders_tracked_independently(self) -> None:
        store = store_with(
            make_order("ord-1", status=OrderStatus.PENDING),
            make_order("ord-2", status=OrderStatus.CONFIRMED),
        )
        poller = OrderStatusPoller(store)
        poller.poll()  # seed both

        received_1: list[Order] = []
        received_2: list[Order] = []
        poller.subscribe("ord-1", received_1.append)
        poller.subscribe("ord-2", received_2.append)

        store.set(make_order("ord-1", status=OrderStatus.CONFIRMED))
        poller.poll()

        assert len(received_1) == 1
        assert received_2 == []

    def test_full_lifecycle_fires_correct_events(self) -> None:
        store = store_with(make_order(status=OrderStatus.PENDING))
        poller = OrderStatusPoller(store)

        received_statuses: list[OrderStatus] = []
        poller.subscribe("ord-1", lambda o: received_statuses.append(o.status))

        transitions = [
            OrderStatus.PENDING,      # initial seed (no callback)
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
            OrderStatus.READY,
            OrderStatus.DELIVERED,
        ]

        for status in transitions:
            store.set(make_order(status=status))
            poller.poll()

        # PENDING is the seed; every subsequent status fires a callback
        assert received_statuses == [
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
            OrderStatus.READY,
            OrderStatus.DELIVERED,
        ]

    def test_failing_callback_does_not_prevent_other_callbacks(self) -> None:
        store = store_with(make_order(status=OrderStatus.PENDING))
        poller = OrderStatusPoller(store)
        poller.poll()

        def bad_callback(order: Order) -> None:
            raise RuntimeError("simulated callback failure")

        good_log: list[Order] = []
        poller.subscribe("ord-1", bad_callback)
        poller.subscribe("ord-1", good_log.append)

        store.set(make_order(status=OrderStatus.CONFIRMED))
        poller.poll()  # bad_callback raises, good_log should still be appended

        assert len(good_log) == 1

    def test_event_contains_correct_order_reference(self) -> None:
        store = store_with(make_order(status=OrderStatus.PENDING))
        poller = OrderStatusPoller(store)
        poller.poll()

        new_order = Order(id="ord-1", shopper_id="s-42", status=OrderStatus.PREPARING)
        store.set(new_order)
        events = poller.poll()

        assert events[0].order is new_order

    def test_cancelled_order_also_clears_subscriptions(self) -> None:
        store = store_with(make_order(status=OrderStatus.PENDING))
        poller = OrderStatusPoller(store)
        poller.poll()

        poller.subscribe("ord-1", lambda o: None)
        store.set(make_order(status=OrderStatus.CANCELLED))
        poller.poll()

        assert poller.subscription_count("ord-1") == 0

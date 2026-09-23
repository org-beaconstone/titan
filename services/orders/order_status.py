"""
Real-time order status visibility for shoppers.

Provides an in-process polling model that tracks order status changes
and notifies registered shopper callbacks as soon as a change is detected.
Each order supports multiple subscribers; callbacks are invoked in
registration order and errors are isolated per-callback.
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


class OrderStatus(enum.Enum):
    """Lifecycle states an order can occupy."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# Terminal states — no further transitions are expected.
TERMINAL_STATUSES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.DELIVERED, OrderStatus.CANCELLED}
)

# Callback type: receives the updated Order when its status changes.
StatusChangeCallback = Callable[["Order"], None]


@dataclass
class Order:
    """Represents a shopper's order and its current status.

    Attributes:
        id: Unique order identifier.
        shopper_id: Identifier of the shopper who placed the order.
        status: Current :class:`OrderStatus`.
        updated_at: Unix timestamp of the last status change.
    """

    id: str
    shopper_id: str
    status: OrderStatus
    updated_at: float = field(default_factory=time.time)

    @property
    def is_terminal(self) -> bool:
        """True when the order has reached a final state."""
        return self.status in TERMINAL_STATUSES


class OrderStatusStore:
    """In-memory store for the current status of all tracked orders.

    Acts as the source of truth consulted by :class:`OrderStatusPoller`
    on each poll cycle. In production this would be backed by a database
    or cache layer; the interface is kept deliberately minimal so that
    the backing implementation can be swapped without touching polling logic.

    Args:
        orders: Optional initial mapping of order_id -> :class:`Order`.

    Example::

        store = OrderStatusStore()
        store.set(Order(id="ord-1", shopper_id="s-42", status=OrderStatus.PENDING))
        order = store.get("ord-1")
    """

    def __init__(self, orders: dict[str, Order] | None = None) -> None:
        self._orders: dict[str, Order] = dict(orders or {})

    def get(self, order_id: str) -> Order | None:
        """Return the current :class:`Order` for *order_id*, or ``None``."""
        return self._orders.get(order_id)

    def set(self, order: Order) -> None:
        """Insert or replace the stored state for *order.id*."""
        self._orders[order.id] = order

    def all_order_ids(self) -> list[str]:
        """Return a snapshot of all tracked order IDs."""
        return list(self._orders.keys())


@dataclass
class StatusChangeEvent:
    """Emitted when an order transitions to a new status.

    Attributes:
        order: The updated :class:`Order` (reflects the new status).
        previous_status: The status immediately before the transition.
    """

    order: Order
    previous_status: OrderStatus


class OrderStatusPoller:
    """Detects order status changes and notifies subscribed shopper callbacks.

    On each call to :meth:`poll` the poller queries *store* for every
    tracked order, compares the current status against its last-known
    snapshot, and fires registered callbacks for any order whose status
    has changed.

    Subscriptions for orders that have reached a terminal state are
    automatically cleaned up after their callbacks are notified, so
    shoppers do not receive spurious future notifications.

    Args:
        store: The :class:`OrderStatusStore` to consult on each poll cycle.

    Example::

        store = OrderStatusStore()
        poller = OrderStatusPoller(store)

        def notify_shopper(order: Order) -> None:
            print(f"Order {order.id} is now {order.status.value}")

        poller.subscribe("ord-1", notify_shopper)

        store.set(Order(id="ord-1", shopper_id="s-42", status=OrderStatus.PENDING))
        poller.poll()   # seeds initial snapshot; no callbacks fired yet

        store.set(Order(id="ord-1", shopper_id="s-42", status=OrderStatus.CONFIRMED))
        poller.poll()   # fires notify_shopper with the updated Order
    """

    def __init__(self, store: OrderStatusStore) -> None:
        self._store = store
        # order_id -> list of callbacks
        self._subscriptions: dict[str, list[StatusChangeCallback]] = {}
        # order_id -> last observed OrderStatus
        self._snapshots: dict[str, OrderStatus] = {}

    def subscribe(self, order_id: str, callback: StatusChangeCallback) -> None:
        """Register *callback* to be invoked whenever *order_id* changes status.

        Multiple callbacks may be registered for the same order; each is
        called independently.  Registering the same callback twice will
        result in it being called twice per event.

        Args:
            order_id: The order to watch.
            callback: A callable that accepts a single :class:`Order` argument.
        """
        self._subscriptions.setdefault(order_id, []).append(callback)
        logger.debug("Subscribed callback for order %s (total=%d).", order_id, len(self._subscriptions[order_id]))

    def unsubscribe(self, order_id: str, callback: StatusChangeCallback) -> None:
        """Remove a previously registered *callback* for *order_id*.

        If the callback is not currently registered this is a no-op.

        Args:
            order_id: The order whose subscription should be modified.
            callback: The callback to remove.
        """
        callbacks = self._subscriptions.get(order_id, [])
        try:
            callbacks.remove(callback)
        except ValueError:
            pass
        if not callbacks:
            self._subscriptions.pop(order_id, None)

    def poll(self) -> list[StatusChangeEvent]:
        """Check every tracked order for status changes and notify subscribers.

        A status change is detected when the order's current status in
        *store* differs from the last snapshot recorded by this poller.
        On the very first poll for a given order the current status is
        recorded as a baseline — no callbacks are fired for that initial
        observation.

        Callbacks for orders that reach a terminal state are removed after
        notification; further polls will not re-fire them.

        Returns:
            A list of :class:`StatusChangeEvent` objects, one per order
            that changed status during this poll cycle (empty list if
            nothing changed).
        """
        events: list[StatusChangeEvent] = []
        order_ids = set(self._store.all_order_ids()) | set(self._snapshots.keys())

        for order_id in order_ids:
            order = self._store.get(order_id)
            if order is None:
                continue

            previous = self._snapshots.get(order_id)

            if previous is None:
                # First observation — seed the snapshot without firing callbacks.
                self._snapshots[order_id] = order.status
                logger.debug("Order %s seeded with initial status %s.", order_id, order.status.value)
                continue

            if order.status == previous:
                continue

            # Status has changed — record and notify.
            self._snapshots[order_id] = order.status
            event = StatusChangeEvent(order=order, previous_status=previous)
            events.append(event)

            logger.info(
                "Order %s status changed: %s -> %s (shopper=%s).",
                order_id,
                previous.value,
                order.status.value,
                order.shopper_id,
            )

            self._fire_callbacks(event)

            if order.is_terminal:
                self._subscriptions.pop(order_id, None)
                logger.debug("Cleared subscriptions for terminal order %s.", order_id)

        return events

    def subscription_count(self, order_id: str) -> int:
        """Return the number of callbacks currently registered for *order_id*."""
        return len(self._subscriptions.get(order_id, []))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fire_callbacks(self, event: StatusChangeEvent) -> None:
        """Invoke all callbacks for the changed order, isolating errors."""
        callbacks = list(self._subscriptions.get(event.order.id, []))
        for callback in callbacks:
            try:
                callback(event.order)
            except Exception as exc:
                logger.error(
                    "Status-change callback failed for order %s: %s",
                    event.order.id,
                    exc,
                )

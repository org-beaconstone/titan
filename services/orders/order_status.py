"""
Real-time order status service for the Titan shopper-facing API.

Provides an in-memory store for order state and a polling-based mechanism
that surfaces live order status changes to shoppers. The poller is designed
to be called on a short interval (e.g. every few seconds) so consumers always
see the latest status without requiring a persistent connection.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    """Lifecycle statuses for a shopper order.

    The progression is: PENDING → CONFIRMED → PROCESSING → SHIPPED →
    OUT_FOR_DELIVERY → DELIVERED.  An order may move to CANCELLED from
    any non-terminal state.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Return True if this status ends the order lifecycle."""
        return self in (OrderStatus.DELIVERED, OrderStatus.CANCELLED)


_VALID_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING: frozenset({OrderStatus.CONFIRMED, OrderStatus.CANCELLED}),
    OrderStatus.CONFIRMED: frozenset({OrderStatus.PROCESSING, OrderStatus.CANCELLED}),
    OrderStatus.PROCESSING: frozenset({OrderStatus.SHIPPED, OrderStatus.CANCELLED}),
    OrderStatus.SHIPPED: frozenset({OrderStatus.OUT_FOR_DELIVERY, OrderStatus.CANCELLED}),
    OrderStatus.OUT_FOR_DELIVERY: frozenset({OrderStatus.DELIVERED, OrderStatus.CANCELLED}),
    OrderStatus.DELIVERED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}


class InvalidStatusTransitionError(Exception):
    """Raised when a status transition is not permitted by the lifecycle rules."""


@dataclass
class OrderStatusEvent:
    """A single timestamped status change on an order.

    Attributes:
        status: The new :class:`OrderStatus` after this event.
        timestamp: Monotonic clock value when the transition occurred.
        note: Optional free-text detail (e.g. carrier message, cancellation reason).
    """

    status: OrderStatus
    timestamp: float = field(default_factory=time.monotonic)
    note: str = ""


@dataclass
class Order:
    """Represents a shopper order with its full status history.

    Attributes:
        order_id: Unique identifier for the order.
        shopper_id: Identifier of the shopper who placed the order.
        status: Current :class:`OrderStatus`.
        history: Ordered list of :class:`OrderStatusEvent` records.
    """

    order_id: str
    shopper_id: str
    status: OrderStatus = OrderStatus.PENDING
    history: list[OrderStatusEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.history:
            self.history.append(OrderStatusEvent(status=self.status))

    def transition(self, new_status: OrderStatus, *, note: str = "") -> None:
        """Advance the order to *new_status*, recording a history event.

        Args:
            new_status: The target :class:`OrderStatus`.
            note: Optional message to attach to the transition event.

        Raises:
            InvalidStatusTransitionError: If the transition is not permitted
                from the current status.
        """
        allowed = _VALID_TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise InvalidStatusTransitionError(
                f"Cannot transition order {self.order_id} from "
                f"{self.status.value!r} to {new_status.value!r}."
            )
        logger.info(
            "Order %s status: %s → %s%s",
            self.order_id,
            self.status.value,
            new_status.value,
            f" ({note})" if note else "",
        )
        self.status = new_status
        self.history.append(OrderStatusEvent(status=new_status, note=note))


class OrderNotFoundError(Exception):
    """Raised when an order cannot be located in the store."""


class OrderStatusStore:
    """In-memory store for shopper orders.

    Provides lookup and mutation operations used by the status service and
    the poller. In production this would be backed by a persistent data store;
    the in-memory implementation supports testing and local development.

    Example::

        store = OrderStatusStore()
        store.add(Order(order_id="ORD-001", shopper_id="USR-42"))
        store.update_status("ORD-001", OrderStatus.CONFIRMED)
        order = store.get("ORD-001")
        print(order.status)  # OrderStatus.CONFIRMED
    """

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def add(self, order: Order) -> None:
        """Register a new order in the store.

        Args:
            order: The :class:`Order` to store.
        """
        self._orders[order.order_id] = order
        logger.debug("Order %s added to store (shopper=%s).", order.order_id, order.shopper_id)

    def get(self, order_id: str) -> Order:
        """Retrieve an order by its ID.

        Args:
            order_id: The unique order identifier.

        Raises:
            OrderNotFoundError: If no order with that ID exists.
        """
        try:
            return self._orders[order_id]
        except KeyError:
            raise OrderNotFoundError(f"Order {order_id!r} not found in store.")

    def update_status(
        self, order_id: str, new_status: OrderStatus, *, note: str = ""
    ) -> Order:
        """Transition *order_id* to *new_status*.

        Args:
            order_id: The order to update.
            new_status: Target :class:`OrderStatus`.
            note: Optional transition note.

        Returns:
            The updated :class:`Order`.

        Raises:
            OrderNotFoundError: If the order does not exist.
            InvalidStatusTransitionError: If the transition is not permitted.
        """
        order = self.get(order_id)
        order.transition(new_status, note=note)
        return order

    def orders_for_shopper(self, shopper_id: str) -> list[Order]:
        """Return all orders belonging to *shopper_id*.

        Args:
            shopper_id: The shopper whose orders to retrieve.

        Returns:
            List of :class:`Order` objects, most recently added last.
        """
        return [o for o in self._orders.values() if o.shopper_id == shopper_id]

    def all_orders(self) -> list[Order]:
        """Return every order currently in the store."""
        return list(self._orders.values())


@dataclass
class StatusUpdate:
    """A status change surfaced by the :class:`OrderStatusPoller`.

    Attributes:
        order_id: The order that changed.
        shopper_id: The shopper who owns the order.
        previous_status: Status before the change (``None`` for new orders).
        current_status: Status at the time of polling.
    """

    order_id: str
    shopper_id: str
    previous_status: OrderStatus | None
    current_status: OrderStatus


class OrderStatusPoller:
    """Detects and surfaces real-time order status changes for shoppers.

    The poller snapshots the status of every watched order on each call to
    :meth:`poll`.  Any order whose status has changed since the last poll is
    returned as a :class:`StatusUpdate`.  Callers are responsible for
    scheduling repeated polls at whatever cadence suits their use case
    (e.g. every few seconds from a background thread or scheduled task).

    Args:
        store: The :class:`OrderStatusStore` to read from.
        shopper_filter: Optional callable that receives a shopper ID and returns
                        ``True`` if that shopper's orders should be watched.
                        When omitted, all orders in the store are watched.

    Example::

        store = OrderStatusStore()
        store.add(Order(order_id="ORD-001", shopper_id="USR-42"))

        poller = OrderStatusPoller(store)
        updates = poller.poll()   # empty on first call — establishes baseline
        # … order status changes elsewhere …
        updates = poller.poll()   # returns StatusUpdate entries for changed orders
    """

    def __init__(
        self,
        store: OrderStatusStore,
        *,
        shopper_filter: Callable[[str], bool] | None = None,
    ) -> None:
        self._store = store
        self._shopper_filter = shopper_filter
        self._last_seen: dict[str, OrderStatus] = {}

    def poll(self) -> list[StatusUpdate]:
        """Compare current order statuses against the last snapshot.

        Returns:
            A list of :class:`StatusUpdate` objects for every order whose
            status has changed (or that is new) since the previous call.
            Returns an empty list when no changes are detected.
        """
        updates: list[StatusUpdate] = []
        orders = self._store.all_orders()

        if self._shopper_filter is not None:
            orders = [o for o in orders if self._shopper_filter(o.shopper_id)]

        for order in orders:
            previous = self._last_seen.get(order.order_id)
            if previous != order.status:
                if previous is not None:
                    logger.info(
                        "Poller detected status change for order %s: %s → %s",
                        order.order_id,
                        previous.value,
                        order.status.value,
                    )
                updates.append(
                    StatusUpdate(
                        order_id=order.order_id,
                        shopper_id=order.shopper_id,
                        previous_status=previous,
                        current_status=order.status,
                    )
                )
                self._last_seen[order.order_id] = order.status

        return updates

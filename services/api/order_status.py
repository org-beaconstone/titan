"""
Real-time order status tracking for shoppers.

Provides a registry of orders and a polling-based tracker that shoppers can
use to receive up-to-date order status without requiring a persistent
connection.  Status changes are recorded as immutable events so that the
full transition history is always available alongside the current state.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class OrderStatus(str, Enum):
    """Lifecycle states an order can occupy.

    Attributes:
        PENDING: Order received but not yet confirmed.
        CONFIRMED: Payment confirmed; awaiting fulfilment.
        PROCESSING: Being picked, packed, or prepared for dispatch.
        SHIPPED: Handed to the carrier; in transit.
        DELIVERED: Successfully delivered to the shopper.
        CANCELLED: Order cancelled before delivery.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# Transitions that are not permitted.
_FORBIDDEN_TRANSITIONS: frozenset[tuple[OrderStatus, OrderStatus]] = frozenset(
    {
        (OrderStatus.DELIVERED, OrderStatus.SHIPPED),
        (OrderStatus.DELIVERED, OrderStatus.PROCESSING),
        (OrderStatus.DELIVERED, OrderStatus.CONFIRMED),
        (OrderStatus.DELIVERED, OrderStatus.PENDING),
        (OrderStatus.CANCELLED, OrderStatus.CONFIRMED),
        (OrderStatus.CANCELLED, OrderStatus.PROCESSING),
        (OrderStatus.CANCELLED, OrderStatus.SHIPPED),
        (OrderStatus.CANCELLED, OrderStatus.DELIVERED),
    }
)

# Terminal states — once reached, no further transitions are valid.
_TERMINAL_STATUSES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.DELIVERED, OrderStatus.CANCELLED}
)


class OrderNotFoundError(Exception):
    """Raised when an order ID is not present in the registry."""


class InvalidStatusTransitionError(Exception):
    """Raised when a requested status transition is not permitted."""


# ---------------------------------------------------------------------------
# Event and order models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatusChangeEvent:
    """An immutable record of a single order-status transition.

    Attributes:
        order_id: Identifier of the order that changed.
        previous_status: Status before the transition (``None`` for the first event).
        new_status: Status after the transition.
        timestamp: Monotonic timestamp (seconds) when the event was recorded.
        note: Optional human-readable annotation (e.g. tracking number).
    """

    order_id: str
    previous_status: OrderStatus | None
    new_status: OrderStatus
    timestamp: float
    note: str = ""


@dataclass
class Order:
    """Represents a shopper's order and its full status history.

    Attributes:
        id: Unique order identifier.
        shopper_id: Identifier of the shopper who placed the order.
        status: Current :class:`OrderStatus`.
        history: Ordered list of :class:`StatusChangeEvent` records.
    """

    id: str
    shopper_id: str
    status: OrderStatus = OrderStatus.PENDING
    history: list[StatusChangeEvent] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        """True if the order has reached a state that permits no further changes."""
        return self.status in _TERMINAL_STATUSES

    @property
    def last_updated(self) -> float | None:
        """Monotonic timestamp of the most recent status change, or ``None``."""
        return self.history[-1].timestamp if self.history else None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class OrderStatusRegistry:
    """Stores orders and enforces valid status transitions.

    Args:
        clock: Callable that returns the current monotonic time in seconds.
               Defaults to :func:`time.monotonic` — override in tests for
               deterministic timestamps.

    Example::

        registry = OrderStatusRegistry()
        registry.register("order-001", shopper_id="shopper-42")
        registry.update_status("order-001", OrderStatus.CONFIRMED)
        order = registry.get("order-001")
        print(order.status)   # OrderStatus.CONFIRMED
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._orders: dict[str, Order] = {}
        self._clock = clock

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, order_id: str, *, shopper_id: str) -> Order:
        """Create a new order in ``PENDING`` status.

        Args:
            order_id: Unique identifier for the order.
            shopper_id: Identifier of the shopper who placed the order.

        Returns:
            The newly created :class:`Order`.
        """
        event = StatusChangeEvent(
            order_id=order_id,
            previous_status=None,
            new_status=OrderStatus.PENDING,
            timestamp=self._clock(),
        )
        order = Order(id=order_id, shopper_id=shopper_id, history=[event])
        self._orders[order_id] = order
        logger.info("Order %s registered for shopper %s.", order_id, shopper_id)
        return order

    def get(self, order_id: str) -> Order:
        """Retrieve an order by ID.

        Args:
            order_id: The order to look up.

        Returns:
            The matching :class:`Order`.

        Raises:
            OrderNotFoundError: If no order with that ID exists.
        """
        try:
            return self._orders[order_id]
        except KeyError:
            raise OrderNotFoundError(f"Order '{order_id}' not found in registry.")

    def update_status(
        self,
        order_id: str,
        new_status: OrderStatus,
        *,
        note: str = "",
    ) -> StatusChangeEvent:
        """Transition an order to a new status.

        Args:
            order_id: The order to update.
            new_status: The target :class:`OrderStatus`.
            note: Optional annotation (e.g. carrier tracking number).

        Returns:
            The :class:`StatusChangeEvent` that was recorded.

        Raises:
            OrderNotFoundError: If the order does not exist.
            InvalidStatusTransitionError: If the transition is forbidden.
        """
        order = self.get(order_id)

        if order.status == new_status:
            logger.debug("Order %s is already in status %s — no-op.", order_id, new_status)
            return order.history[-1]

        if order.is_terminal:
            raise InvalidStatusTransitionError(
                f"Order '{order_id}' is in terminal status {order.status.value!r} "
                "and cannot be updated further."
            )

        if (order.status, new_status) in _FORBIDDEN_TRANSITIONS:
            raise InvalidStatusTransitionError(
                f"Cannot transition order '{order_id}' from "
                f"{order.status.value!r} to {new_status.value!r}."
            )

        event = StatusChangeEvent(
            order_id=order_id,
            previous_status=order.status,
            new_status=new_status,
            timestamp=self._clock(),
            note=note,
        )
        order.status = new_status
        order.history.append(event)
        logger.info(
            "Order %s transitioned %s → %s%s.",
            order_id,
            event.previous_status.value,  # type: ignore[union-attr]
            new_status.value,
            f" ({note})" if note else "",
        )
        return event

    def orders_for_shopper(self, shopper_id: str) -> list[Order]:
        """Return all orders belonging to a given shopper.

        Args:
            shopper_id: The shopper whose orders to retrieve.

        Returns:
            List of :class:`Order` objects (may be empty).
        """
        return [o for o in self._orders.values() if o.shopper_id == shopper_id]


# ---------------------------------------------------------------------------
# Real-time polling tracker
# ---------------------------------------------------------------------------


class OrderStatusPoller:
    """Delivers real-time status updates to a shopper via polling.

    The poller maintains a cursor into the per-order event history.  Each
    call to :meth:`poll` returns only the events that occurred since the
    previous call, so the shopper receives an incremental stream of status
    changes without re-processing the full history.

    Args:
        registry: The :class:`OrderStatusRegistry` to poll.
        order_id: The order to track.
        shopper_id: Used to verify the requesting shopper owns the order.

    Raises:
        OrderNotFoundError: If the order does not exist.
        PermissionError: If ``shopper_id`` does not own the order.

    Example::

        registry = OrderStatusRegistry()
        registry.register("order-001", shopper_id="shopper-42")

        poller = OrderStatusPoller(registry, "order-001", shopper_id="shopper-42")

        # First poll — returns the initial PENDING event.
        events = poller.poll()

        # Update the order externally.
        registry.update_status("order-001", OrderStatus.CONFIRMED)

        # Second poll — returns only the CONFIRMED event.
        events = poller.poll()
    """

    def __init__(
        self,
        registry: OrderStatusRegistry,
        order_id: str,
        *,
        shopper_id: str,
    ) -> None:
        order = registry.get(order_id)
        if order.shopper_id != shopper_id:
            raise PermissionError(
                f"Shopper '{shopper_id}' is not authorised to track order '{order_id}'."
            )
        self._registry = registry
        self._order_id = order_id
        self._cursor: int = 0  # index of the next unseen event in history

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def order_id(self) -> str:
        """The order being tracked."""
        return self._order_id

    @property
    def current_status(self) -> OrderStatus:
        """The live status of the tracked order."""
        return self._registry.get(self._order_id).status

    @property
    def has_new_events(self) -> bool:
        """True if unseen status-change events are available."""
        return self._cursor < len(self._registry.get(self._order_id).history)

    def poll(self) -> list[StatusChangeEvent]:
        """Return all status-change events since the last call.

        Returns:
            A (possibly empty) list of new :class:`StatusChangeEvent` objects
            in chronological order.
        """
        order = self._registry.get(self._order_id)
        new_events = order.history[self._cursor :]
        self._cursor = len(order.history)
        if new_events:
            logger.debug(
                "Poller for order %s delivered %d new event(s); cursor now at %d.",
                self._order_id,
                len(new_events),
                self._cursor,
            )
        return new_events

    def event_stream(
        self,
        *,
        poll_interval: float = 1.0,
        timeout: float | None = None,
    ) -> Iterator[StatusChangeEvent]:
        """Yield status-change events as they arrive until the order is terminal.

        This is a convenience generator for consumers that want a simple
        iteration interface rather than calling :meth:`poll` in a loop.

        Args:
            poll_interval: Seconds to sleep between polling attempts.
            timeout: If given, stop after this many seconds have elapsed
                     (even if the order is not yet terminal).

        Yields:
            :class:`StatusChangeEvent` objects in the order they were recorded.

        Example::

            for event in poller.event_stream(poll_interval=0.5):
                print(event.new_status)
        """
        started = time.monotonic()
        # Yield any events already present before entering the wait loop.
        yield from self.poll()

        while not self._registry.get(self._order_id).is_terminal:
            if timeout is not None and (time.monotonic() - started) >= timeout:
                logger.debug("event_stream timeout reached for order %s.", self._order_id)
                break
            time.sleep(poll_interval)
            yield from self.poll()

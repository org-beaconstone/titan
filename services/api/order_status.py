"""
Real-time order status tracking for Titan shoppers.

Exposes a lightweight polling-based tracker that surfaces the current order
state and a timestamped history of all transitions. The tracker is the
authoritative source of truth consumed by the API layer when shoppers
request order status.

Status transitions follow a strict progression:

    PLACED → CONFIRMED → PROCESSING → SHIPPED → DELIVERED

Cancellations are allowed from any non-terminal state. Attempts to apply
an invalid transition raise :class:`InvalidStatusTransitionError`.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import List, Optional


class OrderStatusValue(enum.Enum):
    """Canonical order status values surfaced to shoppers."""

    PLACED = "placed"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# Terminal states — no further transitions are permitted.
_TERMINAL_STATES: frozenset[OrderStatusValue] = frozenset(
    {OrderStatusValue.DELIVERED, OrderStatusValue.CANCELLED}
)

# Valid forward transitions (excluding CANCELLED which is always allowed
# from non-terminal states).
_VALID_TRANSITIONS: dict[OrderStatusValue, frozenset[OrderStatusValue]] = {
    OrderStatusValue.PLACED: frozenset({OrderStatusValue.CONFIRMED, OrderStatusValue.CANCELLED}),
    OrderStatusValue.CONFIRMED: frozenset({OrderStatusValue.PROCESSING, OrderStatusValue.CANCELLED}),
    OrderStatusValue.PROCESSING: frozenset({OrderStatusValue.SHIPPED, OrderStatusValue.CANCELLED}),
    OrderStatusValue.SHIPPED: frozenset({OrderStatusValue.DELIVERED, OrderStatusValue.CANCELLED}),
    OrderStatusValue.DELIVERED: frozenset(),
    OrderStatusValue.CANCELLED: frozenset(),
}


class InvalidStatusTransitionError(Exception):
    """Raised when a requested status transition is not permitted."""


@dataclass
class StatusEvent:
    """A single recorded status transition.

    Attributes:
        status: The new :class:`OrderStatusValue` after the transition.
        timestamp: Wall-clock time of the transition (``time.time()``).
        note: Optional human-readable note attached to this transition.
    """

    status: OrderStatusValue
    timestamp: float = field(default_factory=time.time)
    note: Optional[str] = None

    @property
    def iso_timestamp(self) -> str:
        """Return the transition timestamp in ISO-8601 format (UTC)."""
        import datetime
        return datetime.datetime.utcfromtimestamp(self.timestamp).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )


class OrderStatusTracker:
    """Tracks and exposes the real-time status of a single order.

    Maintains a full history of status events so shoppers can see not just
    the current state but also when each transition occurred.

    Args:
        order_id: The identifier of the order being tracked.
        initial_status: Starting status (defaults to :attr:`OrderStatusValue.PLACED`).

    Example::

        tracker = OrderStatusTracker(order_id="ORD-1234")
        tracker.transition(OrderStatusValue.CONFIRMED)
        tracker.transition(OrderStatusValue.PROCESSING)
        snapshot = tracker.snapshot()
        # snapshot.current_status == OrderStatusValue.PROCESSING
        # len(snapshot.history) == 3
    """

    def __init__(
        self,
        order_id: str,
        initial_status: OrderStatusValue = OrderStatusValue.PLACED,
    ) -> None:
        self._order_id = order_id
        self._history: List[StatusEvent] = [StatusEvent(status=initial_status)]

    @property
    def order_id(self) -> str:
        """The order identifier being tracked."""
        return self._order_id

    @property
    def current_status(self) -> OrderStatusValue:
        """The most recent :class:`OrderStatusValue` for this order."""
        return self._history[-1].status

    @property
    def is_terminal(self) -> bool:
        """``True`` if the order has reached a terminal state (delivered or cancelled)."""
        return self.current_status in _TERMINAL_STATES

    def transition(self, new_status: OrderStatusValue, *, note: Optional[str] = None) -> StatusEvent:
        """Apply a status transition and record it in the history.

        Args:
            new_status: The target :class:`OrderStatusValue`.
            note: Optional note to attach to the transition event.

        Returns:
            The :class:`StatusEvent` that was recorded.

        Raises:
            InvalidStatusTransitionError: If the transition is not permitted
                from the current state.
        """
        allowed = _VALID_TRANSITIONS.get(self.current_status, frozenset())
        if new_status not in allowed:
            raise InvalidStatusTransitionError(
                f"Cannot transition order {self._order_id} from "
                f"{self.current_status.value!r} to {new_status.value!r}. "
                f"Allowed transitions: {[s.value for s in allowed]}"
            )
        event = StatusEvent(status=new_status, note=note)
        self._history.append(event)
        return event

    def history(self) -> List[StatusEvent]:
        """Return an immutable copy of all recorded status events."""
        return list(self._history)

    def snapshot(self) -> "OrderStatusSnapshot":
        """Return a point-in-time snapshot of the order's current state.

        Use this when responding to shopper status requests — the snapshot
        is safe to serialise and return over the API without further locking.
        """
        return OrderStatusSnapshot(
            order_id=self._order_id,
            current_status=self.current_status,
            is_terminal=self.is_terminal,
            history=self.history(),
            polled_at=time.time(),
        )


@dataclass
class OrderStatusSnapshot:
    """A serialisable point-in-time view of an order's status.

    Attributes:
        order_id: The tracked order identifier.
        current_status: Status at the time of polling.
        is_terminal: Whether the order has reached a terminal state.
        history: Full list of :class:`StatusEvent` records.
        polled_at: Wall-clock time when the snapshot was taken.
    """

    order_id: str
    current_status: OrderStatusValue
    is_terminal: bool
    history: List[StatusEvent]
    polled_at: float

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation of this snapshot.

        Suitable for use as an API response body.
        """
        return {
            "order_id": self.order_id,
            "current_status": self.current_status.value,
            "is_terminal": self.is_terminal,
            "polled_at_iso": _epoch_to_iso(self.polled_at),
            "history": [
                {
                    "status": event.status.value,
                    "timestamp_iso": event.iso_timestamp,
                    "note": event.note,
                }
                for event in self.history
            ],
        }


class OrderStatusRegistry:
    """Central registry of :class:`OrderStatusTracker` instances.

    Provides a single lookup point for the API layer when a shopper requests
    the status of an order. Trackers are created on first access (auto-registration
    of new orders) or can be registered explicitly.

    Example::

        registry = OrderStatusRegistry()
        registry.register("ORD-1234")
        registry.transition("ORD-1234", OrderStatusValue.CONFIRMED)
        snapshot = registry.get_snapshot("ORD-1234")
    """

    def __init__(self) -> None:
        self._trackers: dict[str, OrderStatusTracker] = {}

    def register(
        self,
        order_id: str,
        initial_status: OrderStatusValue = OrderStatusValue.PLACED,
    ) -> OrderStatusTracker:
        """Register a new order and return its tracker.

        Args:
            order_id: The order identifier to register.
            initial_status: Starting status for the tracker.

        Raises:
            ValueError: If *order_id* is already registered.
        """
        if order_id in self._trackers:
            raise ValueError(
                f"Order {order_id!r} is already registered. "
                "Use transition() to update its status."
            )
        tracker = OrderStatusTracker(order_id=order_id, initial_status=initial_status)
        self._trackers[order_id] = tracker
        return tracker

    def get_tracker(self, order_id: str) -> OrderStatusTracker:
        """Return the :class:`OrderStatusTracker` for *order_id*.

        Raises:
            KeyError: If *order_id* has not been registered.
        """
        if order_id not in self._trackers:
            raise KeyError(f"Order {order_id!r} is not tracked by this registry.")
        return self._trackers[order_id]

    def transition(
        self,
        order_id: str,
        new_status: OrderStatusValue,
        *,
        note: Optional[str] = None,
    ) -> StatusEvent:
        """Apply a status transition for the given order.

        Args:
            order_id: The order to update.
            new_status: Target :class:`OrderStatusValue`.
            note: Optional note to attach to the transition.

        Returns:
            The recorded :class:`StatusEvent`.

        Raises:
            KeyError: If *order_id* is not registered.
            InvalidStatusTransitionError: If the transition is not permitted.
        """
        return self.get_tracker(order_id).transition(new_status, note=note)

    def get_snapshot(self, order_id: str) -> OrderStatusSnapshot:
        """Return a status snapshot for *order_id*.

        Raises:
            KeyError: If *order_id* is not registered.
        """
        return self.get_tracker(order_id).snapshot()

    def registered_orders(self) -> List[str]:
        """Return a list of all currently registered order IDs."""
        return list(self._trackers.keys())


def _epoch_to_iso(epoch: float) -> str:
    import datetime
    return datetime.datetime.utcfromtimestamp(epoch).strftime("%Y-%m-%dT%H:%M:%SZ")

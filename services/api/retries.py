"""
Retry budget controls for the Titan API and exporter services.

Implements a time-windowed retry budget to prevent retry amplification
under sustained failure conditions. See ADR-0001 for the policy decision.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from services.api.error_handling import ErrorClass, classify_error

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    """Configuration for retry behaviour.

    Attributes:
        max_attempts: Maximum number of attempts (including the first).
        window_seconds: Time window over which ``max_attempts`` is enforced.
        backoff_factor: Base for exponential backoff — delay = backoff_factor ** attempt.
        retryable_classes: Set of :class:`~error_handling.ErrorClass` values that
                           are eligible for retry. Auth failures and GA blockers
                           are never retried regardless of this setting.
    """

    max_attempts: int = 3
    window_seconds: int = 60
    backoff_factor: float = 1.5
    retryable_classes: frozenset[ErrorClass] = field(
        default_factory=lambda: frozenset({ErrorClass.TIMEOUT, ErrorClass.RATE_LIMITED, ErrorClass.UNKNOWN})
    )


_DEFAULT_POLICY = RetryPolicy()


class RetryBudgetExhausted(Exception):
    """Raised when the retry budget for a time window has been exhausted."""


class RetryBudget:
    """Tracks remaining retry attempts within a rolling time window.

    Prevents retry amplification: if N concurrent jobs all fail and retry
    simultaneously, the budget caps the total number of retries across all
    of them within the window.

    Args:
        policy: The :class:`RetryPolicy` governing this budget.

    Example::

        budget = RetryBudget(RetryPolicy(max_attempts=5, window_seconds=30))

        try:
            budget.consume()   # decrements budget; raises if exhausted
            result = exporter.export_monitor(12345)
        except ExportError as e:
            if should_retry(classify_error(e), budget):
                time.sleep(budget.next_delay())
                budget.consume()
                result = exporter.export_monitor(12345)
    """

    def __init__(self, policy: RetryPolicy = _DEFAULT_POLICY) -> None:
        self._policy = policy
        self._attempts: list[float] = []  # monotonic timestamps of each attempt

    @property
    def remaining(self) -> int:
        """Number of attempts remaining in the current window."""
        self._evict_expired()
        return max(0, self._policy.max_attempts - len(self._attempts))

    @property
    def exhausted(self) -> bool:
        """True if no attempts remain in the current window."""
        return self.remaining == 0

    def consume(self) -> None:
        """Record an attempt, raising :class:`RetryBudgetExhausted` if the budget is empty.

        Raises:
            RetryBudgetExhausted: If no attempts remain in the current window.
        """
        self._evict_expired()
        if self.exhausted:
            raise RetryBudgetExhausted(
                f"Retry budget exhausted — {self._policy.max_attempts} attempts "
                f"used within {self._policy.window_seconds}s window. "
                "See ADR-0001 for the retry budget policy."
            )
        self._attempts.append(time.monotonic())
        logger.debug("Retry budget consumed: %d remaining.", self.remaining)

    def next_delay(self, attempt: int = 0) -> float:
        """Return the backoff delay in seconds for the given attempt number.

        Args:
            attempt: Zero-based attempt index (0 = first retry).

        Returns:
            Delay in seconds.
        """
        return self._policy.backoff_factor ** attempt

    def reset(self) -> None:
        """Clear all recorded attempts, resetting the budget to full."""
        self._attempts.clear()

    def _evict_expired(self) -> None:
        """Remove attempts outside the current time window."""
        cutoff = time.monotonic() - self._policy.window_seconds
        self._attempts = [t for t in self._attempts if t > cutoff]


def should_retry(error_class: ErrorClass, budget: RetryBudget) -> bool:
    """Determine whether a failed request should be retried.

    Auth failures (:attr:`ErrorClass.AUTH_FAILURE`) and GA blockers
    (:attr:`ErrorClass.GA_BLOCKER`) are never retried — they require
    human intervention.

    Args:
        error_class: The classified error from :func:`~error_handling.classify_error`.
        budget: The current :class:`RetryBudget`.

    Returns:
        ``True`` if the request should be retried, ``False`` otherwise.
    """
    if error_class in (ErrorClass.AUTH_FAILURE, ErrorClass.GA_BLOCKER):
        logger.warning("Error class %s is not retryable — escalate immediately.", error_class.name)
        return False

    if budget.exhausted:
        logger.warning("Retry budget exhausted — not retrying.")
        return False

    return error_class in budget._policy.retryable_classes

"""
Timeout defaults and enforcement helpers for the Titan API service.

All outbound requests from the API layer must use a timeout sourced from
:func:`effective_timeout` so that they are covered by the bounded timeout
policy described in the architecture docs.
"""

from __future__ import annotations

import enum

#: Default request timeout in seconds applied when no override is provided.
DEFAULT_TIMEOUT_SECONDS: float = 30.0

#: Hard upper bound — no request may block longer than this.
MAX_TIMEOUT_SECONDS: float = 120.0


class TimeoutPolicy(enum.Enum):
    """Named timeout presets for common Titan request types."""

    DEFAULT = DEFAULT_TIMEOUT_SECONDS
    EXPORT = 60.0
    HEALTH_CHECK = 5.0
    ORDER_STATUS = 10.0


def effective_timeout(
    requested: float | None = None,
    policy: TimeoutPolicy = TimeoutPolicy.DEFAULT,
) -> float:
    """Return the effective timeout to use for a request.

    Clamps *requested* to the hard upper bound. Falls back to *policy* when
    *requested* is ``None``.

    Args:
        requested: Caller-supplied timeout, or ``None`` to use the policy default.
        policy: Named preset used when *requested* is not given.

    Returns:
        Effective timeout in seconds, capped at :data:`MAX_TIMEOUT_SECONDS`.
    """
    base = requested if requested is not None else policy.value
    return min(base, MAX_TIMEOUT_SECONDS)

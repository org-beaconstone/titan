"""
Error classification for the Titan API and worker services.

Provides a stable set of error classes and a classifier function used
by retry logic throughout the platform. See ADR-0001 for the retry
budget policy and ADR-0002 for auth-failure escalation guidance.
"""

from __future__ import annotations

import enum


class ErrorClass(enum.Enum):
    """Canonical error categories used for retry and escalation decisions."""

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTH_FAILURE = "auth_failure"
    GA_BLOCKER = "ga_blocker"
    UNKNOWN = "unknown"


class GABlockerError(Exception):
    """Raised when a GA-blocking condition prevents job execution.

    These errors require human intervention and are never retried automatically.
    See the TPTL-6 GA no-go condition guard in the backfill runner.
    """


def classify_error(exc: BaseException) -> ErrorClass:
    """Classify an exception into a canonical :class:`ErrorClass`.

    Auth failures and GA blockers require immediate escalation and are
    never eligible for automatic retry.

    Args:
        exc: The exception to classify.

    Returns:
        The :class:`ErrorClass` that best describes the error.
    """
    if isinstance(exc, GABlockerError):
        return ErrorClass.GA_BLOCKER

    name = type(exc).__name__.lower()
    message = str(exc).lower()

    if "auth" in name or "auth" in message or "unauthorized" in message or "forbidden" in message:
        return ErrorClass.AUTH_FAILURE

    if "timeout" in name or "timeout" in message or "timed out" in message:
        return ErrorClass.TIMEOUT

    if "ratelimit" in name or "rate limit" in message or "too many requests" in message or "429" in message:
        return ErrorClass.RATE_LIMITED

    return ErrorClass.UNKNOWN

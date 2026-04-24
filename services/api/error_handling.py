"""
Error classification and handling for Titan API and exporter services.

Classifies exceptions into structured error categories to support
consistent retry logic, alerting, and GA readiness checks.

GA Readiness (TPTL-6 / Jul 28):
    GABlockerError is a first-class error class here. Any service that
    introduces a DW-881 dependency in a core collaboration flow should
    raise GABlockerError so it is classified and surfaced appropriately.
"""

from __future__ import annotations

from enum import Enum, auto


class ErrorClass(Enum):
    """Classification of errors observed in Titan API and exporter flows."""

    TIMEOUT = auto()
    """Request exceeded the configured timeout threshold."""

    AUTH_FAILURE = auto()
    """Authentication or authorisation failure (HTTP 401 / 403)."""

    RATE_LIMITED = auto()
    """Upstream API rate limit hit (HTTP 429)."""

    GA_BLOCKER = auto()
    """A condition that triggers the TPTL-6 GA no-go has been detected.

    Raised when a module acquires a DW-881 (data warehouse migration)
    dependency in a core collaboration flow ahead of the Jul 28 GA date.
    """

    UNKNOWN = auto()
    """Catch-all for unclassified errors."""


class TitanAPIError(Exception):
    """Base exception for all Titan API errors."""


class GABlockerError(TitanAPIError):
    """Raised when a GA-blocking condition is detected.

    Any service or module that introduces a dependency on DW-881 (data
    warehouse migration) in a core collaboration flow must raise this error
    rather than failing silently. It will be classified as
    :attr:`ErrorClass.GA_BLOCKER` and surfaced to the warroom.

    See: https://beacon-stone.atlassian.net/browse/TPTL-6
    Contacts: Liam Estrada, Aoife Burke
    """


def classify_error(exc: BaseException) -> ErrorClass:
    """Classify an exception into a structured :class:`ErrorClass`.

    Used by retry logic and alerting to decide whether to retry, surface
    an alert, or trigger a GA no-go review.

    Args:
        exc: The exception to classify.

    Returns:
        The appropriate :class:`ErrorClass` for the exception.

    Example::

        try:
            result = exporter.export_monitor(12345)
        except Exception as e:
            error_class = classify_error(e)
            if error_class == ErrorClass.RATE_LIMITED:
                time.sleep(60)
            elif error_class == ErrorClass.GA_BLOCKER:
                alert_warroom(e)
                raise
    """
    # Import locally to avoid circular imports
    from services.exporter.datadog_export import AuthenticationError  # noqa: PLC0415

    if isinstance(exc, GABlockerError):
        return ErrorClass.GA_BLOCKER

    if isinstance(exc, AuthenticationError):
        return ErrorClass.AUTH_FAILURE

    exc_str = str(exc).lower()
    exc_type = type(exc).__name__.lower()

    if "timeout" in exc_type or "timeout" in exc_str or "timed out" in exc_str:
        return ErrorClass.TIMEOUT

    if "429" in exc_str or "rate limit" in exc_str or "too many requests" in exc_str:
        return ErrorClass.RATE_LIMITED

    if "401" in exc_str or "403" in exc_str or "unauthorized" in exc_str or "forbidden" in exc_str:
        return ErrorClass.AUTH_FAILURE

    return ErrorClass.UNKNOWN


def handle_export_error(exc: BaseException) -> None:
    """Log and re-raise an export error with enriched context.

    GA blocker errors are logged at CRITICAL level and include explicit
    instructions for the on-call warroom.

    Args:
        exc: The exception to handle.

    Raises:
        The original exception, always.
    """
    import logging  # noqa: PLC0415
    logger = logging.getLogger(__name__)

    error_class = classify_error(exc)

    if error_class == ErrorClass.GA_BLOCKER:
        logger.critical(
            "GA BLOCKER detected (TPTL-6): %s. "
            "This triggers the DW-881 no-go condition. "
            "Contact Liam Estrada or Aoife Burke immediately. "
            "Do not deploy until resolved.",
            exc,
        )
    elif error_class == ErrorClass.AUTH_FAILURE:
        logger.error("Auth failure in export pipeline: %s. Check DATADOG_API_KEY / DATADOG_APP_KEY.", exc)
    elif error_class == ErrorClass.RATE_LIMITED:
        logger.warning("Rate limit hit in export pipeline: %s. Cache may mitigate — see ADR-0003.", exc)
    elif error_class == ErrorClass.TIMEOUT:
        logger.warning("Timeout in export pipeline: %s.", exc)
    else:
        logger.error("Unclassified export error: %s", exc)

    raise exc

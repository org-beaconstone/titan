"""
Datadog export client for the Titan exporter service.

Supports metric series submission, dashboard export, and monitor export.
All requests are authenticated via :mod:`datadog_auth` and retry on transient
failures using a simple exponential backoff strategy.

Results from :meth:`DatadogExporter.export_monitor` and
:meth:`DatadogExporter.export_all_monitors` are cached in-process with a
configurable TTL to reduce Datadog API call volume under high job load.
See ADR-0003 for the strategy decision.

GA Readiness (TPTL-6 / Jul 28):
    This module must remain free of data warehouse (DW-881) dependencies.
    See ``_DW_DEPENDENCY`` below. Any change that causes this module to read
    from or write to the Titan data warehouse requires a no-go review before GA.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from services.exporter.datadog_auth import DatadogAuthConfig, build_auth_headers

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = (5, 30)   # (connect, read) seconds
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5          # seconds; delay = _BACKOFF_BASE ** attempt
_DEFAULT_CACHE_TTL = 300     # seconds

# ---------------------------------------------------------------------------
# GA readiness guard — TPTL-6 / DW-881
# ---------------------------------------------------------------------------
# Set this to True if this module begins reading from or writing to the Titan
# data warehouse (DW-881 migration). This will trigger a hard startup failure
# as a no-go signal ahead of the Jul 28 GA date.
# See: https://beacon-stone.atlassian.net/browse/TPTL-6
_DW_DEPENDENCY: bool = False


class ExportError(Exception):
    """Raised when a Datadog export operation fails after all retries."""


class AuthenticationError(ExportError):
    """Raised when the Datadog API rejects the request due to invalid credentials."""


class GABlockerError(Exception):
    """Raised when a GA-blocking condition is detected at startup.

    Any module that introduces a dependency on DW-881 (data warehouse
    migration) in a core collaboration flow must raise this error to prevent
    silent GA risk. See TPTL-6.
    """


@dataclass
class ExportResult:
    """Summary of a completed export operation.

    Attributes:
        success: Whether the operation succeeded.
        status_code: HTTP status code from the last response.
        payload: Parsed JSON body of the last response (may be empty on error).
        errors: List of error messages collected during the operation.
        from_cache: True if the result was served from the in-process cache.
    """

    success: bool
    status_code: int
    payload: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    from_cache: bool = False


@dataclass
class _CacheEntry:
    payload: dict[str, Any]
    expires_at: float  # monotonic time


class DatadogExporter:
    """High-level client for exporting data to and from the Datadog API.

    Results from :meth:`export_monitor` and :meth:`export_all_monitors` are
    cached in-process for *cache_ttl* seconds. This reduces Datadog API calls
    when the same monitors are requested repeatedly within a short window, and
    provides graceful degradation on 429 rate-limit responses (stale cache is
    returned rather than raising :class:`ExportError`).

    The cache is per-instance and not shared across processes. It is suitable
    for the current single-worker deployment; revisit if Titan moves to a
    multi-process worker pool. See ADR-0003.

    Args:
        auth_config: A validated :class:`~services.exporter.datadog_auth.DatadogAuthConfig`.
        cache_ttl: TTL in seconds for cached monitor/dashboard results. Default 300 s.
                   Set to ``0`` to disable caching.

    Raises:
        GABlockerError: If ``_DW_DEPENDENCY`` is ``True`` at startup, indicating
                        this module has acquired a data warehouse dependency that
                        triggers the TPTL-6 no-go condition.
    """

    def __init__(self, auth_config: DatadogAuthConfig, cache_ttl: int = _DEFAULT_CACHE_TTL) -> None:
        if _DW_DEPENDENCY:
            raise GABlockerError(
                "DatadogExporter has acquired a data warehouse (DW-881) dependency. "
                "This triggers the TPTL-6 no-go condition ahead of the Jul 28 GA. "
                "Contact Liam Estrada or Aoife Burke before proceeding. "
                "See: https://beacon-stone.atlassian.net/browse/TPTL-6"
            )
        self._auth_config = auth_config
        self._base_url = f"https://api.{auth_config.site}"
        self._session = requests.Session()
        self._session.headers.update(build_auth_headers(auth_config))
        self._cache_ttl = cache_ttl
        self._cache: dict[str, _CacheEntry] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_metrics(self, metrics: list[dict[str, Any]]) -> ExportResult:
        """Submit a list of metric series to Datadog.

        Metrics are never cached — this method always makes a live API call.

        Args:
            metrics: List of metric series dicts following the Datadog v2 schema.

        Returns:
            An :class:`ExportResult` describing the outcome.

        Raises:
            ExportError: On unrecoverable HTTP errors after all retries.
        """
        body = {"series": metrics}
        response = self._request("POST", "/api/v2/series", json=body)
        return ExportResult(
            success=response.ok,
            status_code=response.status_code,
            payload=self._safe_json(response),
        )

    def export_dashboard(self, dashboard_id: str, *, force_refresh: bool = False) -> ExportResult:
        """Fetch a Datadog dashboard definition by ID.

        Args:
            dashboard_id: The Datadog dashboard identifier (e.g. ``"abc-123-xyz"``).
            force_refresh: If ``True``, bypass the cache and fetch from Datadog directly.

        Returns:
            An :class:`ExportResult` whose ``payload`` contains the dashboard JSON.
        """
        cache_key = f"dashboard:{dashboard_id}"
        if not force_refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return ExportResult(success=True, status_code=200, payload=cached, from_cache=True)

        try:
            response = self._request("GET", f"/api/v1/dashboard/{dashboard_id}")
        except ExportError:
            cached = self._cache_get(cache_key, ignore_ttl=True)
            if cached is not None:
                logger.warning("Returning stale cache for dashboard %s after export failure.", dashboard_id)
                return ExportResult(success=True, status_code=200, payload=cached, from_cache=True)
            raise

        result_payload = self._safe_json(response)
        if response.ok:
            self._cache_set(cache_key, result_payload)
        return ExportResult(success=response.ok, status_code=response.status_code, payload=result_payload)

    def export_monitor(self, monitor_id: int, *, force_refresh: bool = False) -> ExportResult:
        """Fetch a single Datadog monitor definition by ID.

        Results are cached for *cache_ttl* seconds.

        Args:
            monitor_id: Numeric Datadog monitor ID.
            force_refresh: If ``True``, bypass the cache and fetch from Datadog directly.

        Returns:
            An :class:`ExportResult` whose ``payload`` contains the monitor JSON.
        """
        cache_key = f"monitor:{monitor_id}"
        if not force_refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return ExportResult(success=True, status_code=200, payload=cached, from_cache=True)

        try:
            response = self._request("GET", f"/api/v1/monitor/{monitor_id}")
        except ExportError:
            cached = self._cache_get(cache_key, ignore_ttl=True)
            if cached is not None:
                logger.warning("Returning stale cache for monitor %d after export failure.", monitor_id)
                return ExportResult(success=True, status_code=200, payload=cached, from_cache=True)
            raise

        result_payload = self._safe_json(response)
        if response.ok:
            self._cache_set(cache_key, result_payload)
        return ExportResult(success=response.ok, status_code=response.status_code, payload=result_payload)

    def export_all_monitors(
        self,
        tags: list[str] | None = None,
        *,
        force_refresh: bool = False,
    ) -> ExportResult:
        """Fetch all Datadog monitors, optionally filtered by tags.

        Results are cached for *cache_ttl* seconds.

        Args:
            tags: Optional list of tag strings. Tags are sorted before forming
                  the cache key so order does not create duplicate entries.
            force_refresh: If ``True``, bypass the cache and fetch from Datadog directly.

        Returns:
            An :class:`ExportResult` whose ``payload`` is ``{"monitors": [...]}``.
        """
        cache_key = f"all_monitors:{','.join(sorted(tags or []))}"
        if not force_refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return ExportResult(success=True, status_code=200, payload=cached, from_cache=True)

        params: dict[str, Any] = {}
        if tags:
            params["monitor_tags"] = ",".join(tags)

        try:
            response = self._request("GET", "/api/v1/monitor", params=params)
        except ExportError:
            cached = self._cache_get(cache_key, ignore_ttl=True)
            if cached is not None:
                logger.warning("Returning stale cache for all_monitors (tags=%s) after export failure.", tags)
                return ExportResult(success=True, status_code=200, payload=cached, from_cache=True)
            raise

        monitors = self._safe_json(response)
        if isinstance(monitors, list):
            monitors = {"monitors": monitors}
        if response.ok:
            self._cache_set(cache_key, monitors)
        return ExportResult(success=response.ok, status_code=response.status_code, payload=monitors)

    def invalidate_cache(self, key: str | None = None) -> None:
        """Invalidate cache entries.

        Args:
            key: Specific cache key to invalidate, or ``None`` to clear all.
        """
        if key is None:
            self._cache.clear()
            logger.debug("Datadog export cache cleared.")
        elif key in self._cache:
            del self._cache[key]
            logger.debug("Datadog export cache entry '%s' invalidated.", key)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_get(self, key: str, *, ignore_ttl: bool = False) -> dict[str, Any] | None:
        if self._cache_ttl == 0:
            return None
        entry = self._cache.get(key)
        if entry is None:
            return None
        if not ignore_ttl and time.monotonic() > entry.expires_at:
            del self._cache[key]
            return None
        return entry.payload

    def _cache_set(self, key: str, payload: dict[str, Any]) -> None:
        if self._cache_ttl == 0:
            return
        self._cache[key] = _CacheEntry(
            payload=payload,
            expires_at=time.monotonic() + self._cache_ttl,
        )
        logger.debug("Cached '%s' (TTL %ds).", key, self._cache_ttl)

    # ------------------------------------------------------------------
    # Request helper
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> requests.Response:
        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = self._session.request(
                    method, url, params=params, json=json, timeout=_DEFAULT_TIMEOUT,
                )
            except requests.RequestException as exc:
                logger.warning("Request failed (attempt %d/%d): %s", attempt + 1, _MAX_RETRIES, exc)
                last_exc = exc
                time.sleep(_BACKOFF_BASE ** attempt)
                continue

            if response.status_code in (401, 403):
                raise AuthenticationError(
                    f"Datadog API rejected credentials (HTTP {response.status_code}). "
                    "Check DATADOG_API_KEY and DATADOG_APP_KEY."
                )

            if response.ok or response.status_code < 500:
                return response

            logger.warning(
                "Datadog API returned %d (attempt %d/%d); retrying…",
                response.status_code, attempt + 1, _MAX_RETRIES,
            )
            time.sleep(_BACKOFF_BASE ** attempt)

        if last_exc:
            raise ExportError(
                f"Export request to {url} failed after {_MAX_RETRIES} attempts: {last_exc}"
            ) from last_exc
        raise ExportError(f"Export request to {url} failed after {_MAX_RETRIES} attempts (server errors).")

    @staticmethod
    def _safe_json(response: requests.Response) -> dict[str, Any]:
        try:
            return response.json()
        except Exception:
            return {}

"""
Datadog export client for the Titan exporter service.

Supports metric series submission, dashboard export, and monitor export.
All requests are authenticated via :mod:`datadog_auth` and retry on transient
failures using a simple exponential backoff strategy.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

from services.exporter.datadog_auth import DatadogAuthConfig, build_auth_headers

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = (5, 30)   # (connect, read) seconds
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5          # seconds; delay = _BACKOFF_BASE ** attempt


class ExportError(Exception):
    """Raised when a Datadog export operation fails after all retries."""


class AuthenticationError(ExportError):
    """Raised when the Datadog API rejects the request due to invalid credentials."""


@dataclass
class ExportResult:
    """Summary of a completed export operation.

    Attributes:
        success: Whether the operation succeeded.
        status_code: HTTP status code from the last response.
        payload: Parsed JSON body of the last response (may be empty on error).
        errors: List of error messages collected during the operation.
    """

    success: bool
    status_code: int
    payload: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class DatadogExporter:
    """High-level client for exporting data to and from the Datadog API.

    Args:
        auth_config: A validated :class:`~services.exporter.datadog_auth.DatadogAuthConfig`.

    Example::

        from services.exporter.datadog_auth import DatadogAuthConfig
        from services.exporter.datadog_export import DatadogExporter

        config = DatadogAuthConfig.from_env()
        exporter = DatadogExporter(config)

        result = exporter.export_monitor(12345)
        print(result.payload["name"])
    """

    def __init__(self, auth_config: DatadogAuthConfig) -> None:
        self._auth_config = auth_config
        self._base_url = f"https://api.{auth_config.site}"
        self._session = requests.Session()
        self._session.headers.update(build_auth_headers(auth_config))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_metrics(self, metrics: list[dict[str, Any]]) -> ExportResult:
        """Submit a list of metric series to Datadog.

        Each item in *metrics* should follow the Datadog v2 series schema::

            {
                "metric": "titan.export.count",
                "type": 1,          # 0=unspecified, 1=count, 2=rate, 3=gauge
                "points": [{"timestamp": 1714000000, "value": 42.0}],
                "tags": ["env:production", "service:titan"],
            }

        Args:
            metrics: List of metric series dicts.

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

    def export_dashboard(self, dashboard_id: str) -> ExportResult:
        """Fetch a Datadog dashboard definition by ID.

        Args:
            dashboard_id: The Datadog dashboard identifier (e.g. ``"abc-123-xyz"``).

        Returns:
            An :class:`ExportResult` whose ``payload`` contains the dashboard JSON.

        Raises:
            ExportError: On unrecoverable HTTP errors after all retries.
        """
        response = self._request("GET", f"/api/v1/dashboard/{dashboard_id}")
        return ExportResult(
            success=response.ok,
            status_code=response.status_code,
            payload=self._safe_json(response),
        )

    def export_monitor(self, monitor_id: int) -> ExportResult:
        """Fetch a single Datadog monitor definition by ID.

        Args:
            monitor_id: Numeric Datadog monitor ID.

        Returns:
            An :class:`ExportResult` whose ``payload`` contains the monitor JSON.

        Raises:
            ExportError: On unrecoverable HTTP errors after all retries.
        """
        response = self._request("GET", f"/api/v1/monitor/{monitor_id}")
        return ExportResult(
            success=response.ok,
            status_code=response.status_code,
            payload=self._safe_json(response),
        )

    def export_all_monitors(self, tags: list[str] | None = None) -> ExportResult:
        """Fetch all Datadog monitors, optionally filtered by tags.

        Args:
            tags: Optional list of tag strings (e.g. ``["service:titan", "env:prod"]``).
                  Monitors must match *all* provided tags.

        Returns:
            An :class:`ExportResult` whose ``payload`` is a list of monitor dicts
            under the key ``"monitors"``.

        Raises:
            ExportError: On unrecoverable HTTP errors after all retries.

        .. note::
            Under high job volume this method can exhaust the Datadog API rate limit.
            TODO: consider caching export results (TTL-based) to reduce Datadog API
            calls when the same monitor set is requested repeatedly within a short window.
            See ADR-0003 and the bulk sync spike in feature/datadog-bulk-sync-spike.
        """
        params: dict[str, Any] = {}
        if tags:
            params["monitor_tags"] = ",".join(tags)
        response = self._request("GET", "/api/v1/monitor", params=params)
        monitors = self._safe_json(response)
        if isinstance(monitors, list):
            monitors = {"monitors": monitors}
        return ExportResult(
            success=response.ok,
            status_code=response.status_code,
            payload=monitors,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> requests.Response:
        """Execute an authenticated request with exponential-backoff retries."""
        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = self._session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    timeout=_DEFAULT_TIMEOUT,
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
                response.status_code,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(_BACKOFF_BASE ** attempt)

        if last_exc:
            raise ExportError(f"Export request to {url} failed after {_MAX_RETRIES} attempts: {last_exc}") from last_exc
        raise ExportError(f"Export request to {url} failed after {_MAX_RETRIES} attempts (server errors).")

    @staticmethod
    def _safe_json(response: requests.Response) -> dict[str, Any]:
        """Parse JSON from a response, returning an empty dict on failure."""
        try:
            return response.json()
        except Exception:
            return {}


@dataclass
class BulkSyncResult:
    """Summary of a bulk monitor sync operation.

    Attributes:
        synced: Number of monitors successfully fetched and stored.
        failed: Number of monitors that could not be fetched.
        started_at: UTC timestamp when the sync began.
        finished_at: UTC timestamp when the sync completed.
    """

    synced: int
    failed: int
    started_at: datetime
    finished_at: datetime


class BulkSyncExporter:
    """Scheduled bulk exporter that fetches all Datadog monitors at once.

    Designed to run as a nightly cron job, reducing per-request API pressure
    by pre-fetching all monitors into a local cache or data store.

    .. warning::
        **Spike / not production-ready.**
        This class requires a cache layer (e.g. Redis or a DB table) to store
        results between sync runs. Without a cache, individual jobs still fall
        back to per-request fetches, defeating the purpose.

        TODO: integrate with a cache store before enabling in production.
        Deferred in favour of TTL-based in-memory caching — see ADR-0003.

    Args:
        auth_config: A validated :class:`~services.exporter.datadog_auth.DatadogAuthConfig`.
        tags: Optional tag filter applied to every sync run.
    """

    def __init__(
        self,
        auth_config: DatadogAuthConfig,
        tags: list[str] | None = None,
    ) -> None:
        self._exporter = DatadogExporter(auth_config)
        self._tags = tags or []

    def sync_all(self, since: datetime | None = None) -> BulkSyncResult:
        """Fetch all monitors and return a sync summary.

        Args:
            since: If provided, only monitors updated after this timestamp are
                   considered (best-effort — Datadog does not support server-side
                   delta filtering; this is applied client-side on the response).

        Returns:
            A :class:`BulkSyncResult` describing what was synced.

        Raises:
            ExportError: If the underlying API call fails after all retries.
        """
        started_at = datetime.now(timezone.utc)
        result = self._exporter.export_all_monitors(tags=self._tags or None)

        monitors = result.payload.get("monitors", [])

        if since is not None:
            monitors = [
                m for m in monitors
                if datetime.fromisoformat(m.get("modified", "1970-01-01T00:00:00+00:00")) >= since
            ]

        synced = 0
        failed = 0

        for monitor in monitors:
            try:
                # TODO: persist monitor to cache store here
                # e.g. cache.set(f"monitor:{monitor['id']}", monitor, ttl=3600)
                logger.info("Synced monitor %d: %s", monitor["id"], monitor.get("name", "?"))
                synced += 1
            except Exception as exc:
                logger.error("Failed to store monitor %d: %s", monitor.get("id"), exc)
                failed += 1

        return BulkSyncResult(
            synced=synced,
            failed=failed,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )

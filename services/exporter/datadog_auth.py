"""
Datadog authentication helpers for the Titan exporter service.

Credentials are loaded from environment variables and validated before use.
All outbound Datadog API requests must be constructed using :func:`build_auth_headers`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class AuthConfigError(Exception):
    """Raised when Datadog auth configuration is missing or malformed."""


@dataclass
class DatadogAuthConfig:
    """Holds Datadog API credentials and site configuration.

    Attributes:
        api_key: Datadog API key (DD-API-KEY header).
        app_key: Datadog Application key (DD-APPLICATION-KEY header).
        site: Datadog site hostname, e.g. ``datadoghq.com`` or ``datadoghq.eu``.
    """

    api_key: str
    app_key: str
    site: str = field(default="datadoghq.com")

    @classmethod
    def from_env(cls) -> "DatadogAuthConfig":
        """Construct a :class:`DatadogAuthConfig` from environment variables.

        Reads ``DATADOG_API_KEY``, ``DATADOG_APP_KEY``, and optionally
        ``DATADOG_SITE`` (defaults to ``datadoghq.com``).

        Raises:
            AuthConfigError: If either required key is not set.
        """
        api_key = os.environ.get("DATADOG_API_KEY", "")
        app_key = os.environ.get("DATADOG_APP_KEY", "")
        site = os.environ.get("DATADOG_SITE", "datadoghq.com")
        config = cls(api_key=api_key, app_key=app_key, site=site)
        validate_auth_config(config)
        return config


def validate_auth_config(config: DatadogAuthConfig) -> None:
    """Validate that a :class:`DatadogAuthConfig` contains non-empty credentials.

    Args:
        config: The auth config to validate.

    Raises:
        AuthConfigError: If ``api_key`` or ``app_key`` is empty.
    """
    if not config.api_key:
        raise AuthConfigError(
            "DATADOG_API_KEY is not set. Export the key before starting the exporter."
        )
    if not config.app_key:
        raise AuthConfigError(
            "DATADOG_APP_KEY is not set. Export the key before starting the exporter."
        )


def build_auth_headers(config: DatadogAuthConfig) -> dict[str, str]:
    """Return HTTP headers required to authenticate against the Datadog API.

    Args:
        config: A validated :class:`DatadogAuthConfig`.

    Returns:
        A dict with ``DD-API-KEY`` and ``DD-APPLICATION-KEY`` headers.

    Example::

        config = DatadogAuthConfig.from_env()
        headers = build_auth_headers(config)
        # {"DD-API-KEY": "...", "DD-APPLICATION-KEY": "..."}
    """
    return {
        "DD-API-KEY": config.api_key,
        "DD-APPLICATION-KEY": config.app_key,
        "Content-Type": "application/json",
    }

"""Launch diagnostic helpers for Titan review workflows."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DiagnosticSignal:
    name: str
    status: str
    owner: str


def summarize_launch_signals(signals: list[DiagnosticSignal]) -> dict[str, int]:
    """Return a compact status count for launch-readiness review."""
    summary: dict[str, int] = {}
    for signal in signals:
        summary[signal.status] = summary.get(signal.status, 0) + 1
    return summary


def has_blocking_signal(signals: list[DiagnosticSignal]) -> bool:
    """Flag whether launch review should pause for a blocking diagnostic."""
    return any(signal.status == "blocked" for signal in signals)

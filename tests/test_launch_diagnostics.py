"""Regression tests for the launch signal classification preserved from PR #34."""

import unittest

from services.api.launch_diagnostics import (
    DiagnosticSignal,
    has_blocking_signal,
    summarize_launch_signals,
)


class LaunchDiagnosticsTests(unittest.TestCase):
    def test_counts_ready_watch_and_blocked(self):
        signals = [
            DiagnosticSignal("retry-budget", "ready", "platform"),
            DiagnosticSignal("datadog-export", "watch", "sre"),
            DiagnosticSignal("worker-replay", "blocked", "platform"),
            DiagnosticSignal("release-notes", "ready", "support"),
        ]
        self.assertEqual(summarize_launch_signals(signals), {"ready": 2, "watch": 1, "blocked": 1})
        self.assertTrue(has_blocking_signal(signals))

    def test_empty_and_watch_only_are_not_blocked(self):
        self.assertEqual(summarize_launch_signals([]), {})
        self.assertFalse(has_blocking_signal([]))
        self.assertFalse(has_blocking_signal([DiagnosticSignal("export", "watch", "sre")]))


if __name__ == "__main__":
    unittest.main()

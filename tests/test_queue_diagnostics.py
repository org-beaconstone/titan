"""Smoke checks for the Titan queue handoff guardrail."""

import unittest

from services.worker.queue_diagnostics import queue_handoff_summary


class QueueHandoffSummaryTest(unittest.TestCase):
    def test_draining_queue_at_guardrail_is_healthy(self):
        self.assertEqual(
            queue_handoff_summary(queue_depth=250, draining=True)["state"],
            "healthy",
        )

    def test_queue_above_guardrail_requires_attention(self):
        self.assertEqual(
            queue_handoff_summary(queue_depth=251, draining=True)["state"],
            "attention_required",
        )

    def test_non_draining_queue_requires_attention(self):
        self.assertEqual(
            queue_handoff_summary(queue_depth=0, draining=False)["state"],
            "attention_required",
        )


if __name__ == "__main__":
    unittest.main()

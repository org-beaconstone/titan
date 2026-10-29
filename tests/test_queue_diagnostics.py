"""Check the launch handoff's queue telemetry guardrails."""

import unittest

from services.worker.queue_diagnostics import queue_handoff_summary


class QueueHandoffSummaryTest(unittest.TestCase):
    def test_negative_depth_is_not_healthy(self):
        summary = queue_handoff_summary(queue_depth=-1, draining=True)
        self.assertEqual(summary["state"], "attention_required")
        self.assertIn("invalid", summary["detail"])

    def test_queue_at_guardrail_is_healthy_when_draining(self):
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

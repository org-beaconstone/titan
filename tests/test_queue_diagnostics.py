"""Checks for backward compatibility and stale queue-sample handling."""

import unittest

from services.worker.queue_diagnostics import queue_handoff_summary


class QueueHandoffTests(unittest.TestCase):
    def test_existing_callers_retain_previous_results(self):
        self.assertEqual(queue_handoff_summary(queue_depth=250, draining=True)["state"], "healthy")
        self.assertEqual(queue_handoff_summary(queue_depth=251, draining=True)["state"], "attention_required")
        self.assertEqual(queue_handoff_summary(queue_depth=0, draining=False)["state"], "attention_required")

    def test_fresh_and_at_limit_are_not_stale(self):
        for age in (0, 299, 300):
            with self.subTest(age=age):
                self.assertEqual(
                    queue_handoff_summary(queue_depth=5, draining=True, sample_age_seconds=age)["state"],
                    "healthy",
                )

    def test_old_or_invalid_sample_needs_attention(self):
        for age in (301, -1, float("nan"), float("inf")):
            with self.subTest(age=age):
                result = queue_handoff_summary(queue_depth=5, draining=True, sample_age_seconds=age)
                self.assertEqual(result["state"], "attention_required")
                self.assertIn("observation", result["detail"])

    def test_threshold_can_be_configured(self):
        self.assertEqual(queue_handoff_summary(queue_depth=5, draining=True, sample_age_seconds=61, max_sample_age_seconds=60)["state"], "attention_required")
        self.assertEqual(queue_handoff_summary(queue_depth=5, draining=True, sample_age_seconds=60, max_sample_age_seconds=60)["state"], "healthy")

    def test_bad_threshold_fails_closed_at_configuration(self):
        for threshold in (0, -1, float("nan"), float("inf")):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    queue_handoff_summary(queue_depth=5, draining=True, max_sample_age_seconds=threshold)


if __name__ == "__main__":
    unittest.main()

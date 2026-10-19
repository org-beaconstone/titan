"""Customer onboarding signals are a review aid, not launch sign-off."""

import unittest

from services.api.customer_onboarding_readiness import (
    OnboardingSignal,
    onboarding_needs_follow_up,
    onboarding_summary,
)


class OnboardingReadinessTests(unittest.TestCase):
    def signal(self, **overrides):
        fields = dict(
            customer="Beaconstone",
            jira_project_key="TPTL",
            repository="org-beaconstone/titan",
            linked_work_items=18,
            unlinked_pull_requests=0,
            support_note_present=True,
            unresolved_onboarding_blockers=0,
        )
        fields.update(overrides)
        return OnboardingSignal(**fields)

    def test_unlinked_pull_requests_require_follow_up(self):
        signal = self.signal(unlinked_pull_requests=4)
        self.assertTrue(onboarding_needs_follow_up(signal))
        self.assertIn("needs follow-up", onboarding_summary(signal))

    def test_explicitly_clear_blockers_and_support_note_can_be_ready(self):
        signal = self.signal()
        self.assertFalse(onboarding_needs_follow_up(signal))
        self.assertTrue(onboarding_summary(signal).endswith("ready"))

    def test_unresolved_blocker_requires_follow_up(self):
        self.assertTrue(onboarding_needs_follow_up(self.signal(unresolved_onboarding_blockers=1)))

    def test_missing_blocker_evidence_requires_follow_up(self):
        self.assertTrue(onboarding_needs_follow_up(self.signal(unresolved_onboarding_blockers=None)))
        # Existing callers that omit this new field cannot silently report ready.
        previous_caller = OnboardingSignal("Beaconstone", "TPTL", "org-beaconstone/titan", 18, 0, True)
        self.assertTrue(onboarding_needs_follow_up(previous_caller))

    def test_missing_support_note_requires_follow_up(self):
        self.assertTrue(onboarding_needs_follow_up(self.signal(support_note_present=False)))

    def test_no_linked_jira_work_items_requires_follow_up(self):
        self.assertTrue(onboarding_needs_follow_up(self.signal(linked_work_items=0)))

    def test_negative_counts_are_invalid(self):
        for field in ("unresolved_onboarding_blockers", "linked_work_items", "unlinked_pull_requests"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.signal(**{field: -1})


if __name__ == "__main__":
    unittest.main()

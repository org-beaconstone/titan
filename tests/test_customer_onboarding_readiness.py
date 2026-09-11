from services.api.customer_onboarding_readiness import OnboardingSignal, onboarding_needs_follow_up, onboarding_summary


def test_unlinked_pull_requests_require_follow_up():
    signal = OnboardingSignal("Beaconstone", "TPTL", "org-beaconstone/titan", 18, 4, True)

    assert onboarding_needs_follow_up(signal) is True
    assert "needs follow-up" in onboarding_summary(signal)


def test_complete_support_note_and_no_unlinked_prs_is_ready():
    signal = OnboardingSignal("Beaconstone", "TPTL", "org-beaconstone/titan", 18, 0, True)

    assert onboarding_needs_follow_up(signal) is False
    assert onboarding_summary(signal).endswith("ready")

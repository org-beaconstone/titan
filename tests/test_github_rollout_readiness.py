from services.api.github_rollout_readiness import RolloutSignal, rollout_needs_follow_up, rollout_summary


def test_unlinked_pull_requests_require_follow_up():
    signal = RolloutSignal("Beaconstone", "TPTL", "org-beaconstone", 18, 4, True)

    assert rollout_needs_follow_up(signal) is True
    assert "needs follow-up" in rollout_summary(signal)


def test_complete_support_note_and_no_unlinked_prs_is_ready():
    signal = RolloutSignal("Beaconstone", "TPTL", "org-beaconstone", 18, 0, True)

    assert rollout_needs_follow_up(signal) is False
    assert rollout_summary(signal).endswith("ready")

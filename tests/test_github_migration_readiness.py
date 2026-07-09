from services.api.github_migration_readiness import MigrationSignal, migration_needs_follow_up, migration_summary


def test_unlinked_pull_requests_require_follow_up():
    signal = MigrationSignal("Beaconstone", "TPTL", "org-beaconstone", 18, 4, True)

    assert migration_needs_follow_up(signal) is True
    assert "needs follow-up" in migration_summary(signal)


def test_complete_support_note_and_no_unlinked_prs_is_ready():
    signal = MigrationSignal("Beaconstone", "TPTL", "org-beaconstone", 18, 0, True)

    assert migration_needs_follow_up(signal) is False
    assert migration_summary(signal).endswith("ready")

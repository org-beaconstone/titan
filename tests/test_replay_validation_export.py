from services.worker.replay_validation_export import ReplayValidationEvidence, export_replay_validation


def test_replay_validation_export_marks_clean_window_ready():
    payload = export_replay_validation(ReplayValidationEvidence("Beaconstone", "2026-07-10", 128, 0))

    assert payload["status"] == "ready"
    assert payload["validated_jobs"] == 128


def test_replay_validation_export_marks_failures_for_review():
    payload = export_replay_validation(ReplayValidationEvidence("Beaconstone", "2026-07-10", 127, 1))

    assert payload["status"] == "needs_review"

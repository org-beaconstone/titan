from services.worker.backfill_dry_run import BackfillCandidate, plan_retry_backfill


def test_backfill_plan_respects_retry_budget():
    plan = plan_retry_backfill([
        BackfillCandidate(tenant_id="acme", failed_jobs=12, retry_budget=5),
    ])[0]

    assert plan.jobs_to_replay == 5
    assert plan.skipped_jobs == 7
    assert plan.requires_approval is True


def test_high_priority_backfill_requires_approval():
    plan = plan_retry_backfill([
        BackfillCandidate(tenant_id="globex", failed_jobs=2, retry_budget=5, priority="high"),
    ])[0]

    assert plan.jobs_to_replay == 2
    assert plan.skipped_jobs == 0
    assert plan.requires_approval is True

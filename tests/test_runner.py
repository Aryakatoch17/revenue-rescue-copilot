from app.enums import Policy
from app.runner import approve_all_queued, run_policy
from app.seed import seed


def test_agent_beats_baseline_on_frozen_batch():
    assert seed() >= 50
    b = run_policy(Policy.BASELINE, seed=7)
    a = run_policy(Policy.AGENT, seed=7)
    assert a["illegal_contacts"] == 0
    assert b["illegal_contacts"] == 0
    approve_all_queued(a["id"], True)
    approve_all_queued(b["id"], True)
    from app.runner import latest_runs

    runs = {r["policy"]: r for r in latest_runs()}
    assert runs["agent"]["recovered_paise"] > runs["baseline"]["recovered_paise"]
    assert runs["agent"]["diagnosis_correct"] / runs["agent"]["diagnosis_total"] >= 0.7

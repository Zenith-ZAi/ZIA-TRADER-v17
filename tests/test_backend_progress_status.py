import pytest

from scripts.backend_progress_status import build_progress_snapshot


def test_gate_snapshot_has_stable_denominator_and_does_not_authorize_live():
    before = build_progress_snapshot("- [x] contrato A\n- [ ] contrato B\n", phase="before")
    after = build_progress_snapshot("- [x] contrato A\n- [x] contrato B\n", phase="after")
    assert before["accepted_gates"] == 1 and before["total_gates"] == 2
    assert after["accepted_gates"] == after["total_gates"] == 2
    assert before["criteria_sha256"] == after["criteria_sha256"]
    assert after["progress_percent"] == 100
    assert before["grants_live_authorization"] is False


@pytest.mark.parametrize("text,error", [
    ("sem checklist", "progress_criteria_missing"),
    ("- [?] contrato A", "invalid_progress_criterion"),
    ("- [x] contrato A\n- [ ] contrato A", "duplicate_progress_criterion"),
])
def test_gate_snapshot_rejects_unreliable_denominators(text, error):
    with pytest.raises(ValueError, match=f"^{error}$"):
        build_progress_snapshot(text, phase="invalid")

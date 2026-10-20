from learning import model_drift_scheduler


def test_scheduler_evaluates_each_dataset_hash_once_and_persists_across_restart(tmp_path, monkeypatch):
    dataset = tmp_path / "recent.csv"
    dataset.write_text("timestamp,open,high,low,close,volume\n2026-01-01,1,1,1,1,1\n", encoding="utf-8")
    model_dir = tmp_path / "models"
    calls = []

    def monitor(path, root, **kwargs):
        calls.append((path, root, kwargs))
        return {"status": "within_threshold", "hold": False, "model_version": "model-v1"}

    monkeypatch.setattr(model_drift_scheduler, "monitor_model_drift", monitor)
    first = model_drift_scheduler.run_scheduler(dataset, model_dir, registry_store=object(), once=True)
    assert first["status"] == "within_threshold"
    assert len(calls) == 1

    unchanged = model_drift_scheduler.run_scheduler(dataset, model_dir, registry_store=object(), once=True)
    assert unchanged["status"] == "unchanged_dataset"
    assert len(calls) == 1

    dataset.write_text(dataset.read_text(encoding="utf-8") + "2026-01-02,1,1,1,1,1\n", encoding="utf-8")
    changed = model_drift_scheduler.run_scheduler(dataset, model_dir, registry_store=object(), once=True)
    assert changed["status"] == "within_threshold"
    assert len(calls) == 2


def test_scheduler_waits_safely_for_dataset_without_starting_trading(tmp_path):
    result = model_drift_scheduler.run_scheduler(
        tmp_path / "not-ready.csv",
        tmp_path / "models",
        registry_store=object(),
        once=True,
    )
    assert result["status"] == "waiting_for_dataset"

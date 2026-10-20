"""Agendador persistente, idempotente e somente de monitoramento de drift."""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.dataset_integrity import sha256_file
from learning.model_drift import monitor_model_drift
from learning.model_registry import ModelRegistryStore

logger = logging.getLogger("zia.model_drift_scheduler")


def _load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return state if isinstance(state, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.exception("Estado do scheduler ilegível; dataset será reavaliado de forma segura.")
        return {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def run_scheduler(
    dataset_path: str | Path,
    model_dir: str | Path,
    *,
    registry_store: Any,
    interval_seconds: int = 3600,
    min_rows: int = 30,
    window_rows: int = 256,
    report_path: str | Path | None = None,
    once: bool = False,
) -> dict[str, Any]:
    """Avalia cada versão do dataset uma única vez e mantém HOLDs existentes."""
    interval_seconds = int(interval_seconds)
    if interval_seconds < 5 or int(min_rows) < 1 or int(window_rows) < 1:
        raise ValueError("interval_seconds deve ser >= 5; min_rows/window_rows devem ser positivos")
    dataset = Path(dataset_path)
    root = Path(model_dir)
    state_path = root / "drift_scheduler_state.json"
    state = _load_state(state_path)
    last_hash = str(state.get("dataset_sha256") or "")

    while True:
        if not dataset.is_file():
            result = {"status": "waiting_for_dataset", "dataset_path": str(dataset)}
            logger.warning("Dataset de drift ainda não está disponível: %s", dataset)
        else:
            try:
                dataset_hash = sha256_file(dataset)
                if dataset_hash == last_hash:
                    result = {"status": "unchanged_dataset", "dataset_sha256": dataset_hash}
                    logger.info("Dataset de drift não mudou; nenhuma avaliação duplicada.")
                else:
                    result = monitor_model_drift(
                        dataset,
                        root,
                        registry_store=registry_store,
                        window_rows=int(window_rows),
                        min_rows=int(min_rows),
                        report_path=report_path,
                    )
                    state = {
                        "dataset_sha256": dataset_hash,
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "status": result.get("status"),
                        "hold": bool(result.get("hold", False)),
                        "model_version": result.get("model_version"),
                    }
                    _write_state(state_path, state)
                    last_hash = dataset_hash
                    logger.info("Drift avaliado: %s", json.dumps(result, ensure_ascii=False, default=str))
            except Exception:
                # Não avança o hash em erro: retry após o intervalo é idempotente.
                logger.exception("Falha na avaliação de drift; nenhuma aprovação/promoção foi executada.")
                result = {"status": "evaluation_error", "dataset_sha256": last_hash}
        if once:
            return result
        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="/app/data/model_drift_latest.csv")
    parser.add_argument("--model-dir", default="/app/models")
    parser.add_argument("--interval-seconds", type=int, default=3600)
    parser.add_argument("--min-rows", type=int, default=30)
    parser.add_argument("--window-rows", type=int, default=256)
    parser.add_argument("--report-path", default="/app/data/model_drift_reports/latest.json")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    from config.settings import settings
    from database_manager import DatabaseManager

    db_manager = DatabaseManager(settings.DATABASE_URL)
    try:
        db_manager.create_tables()
        result = run_scheduler(
            args.dataset,
            args.model_dir,
            registry_store=ModelRegistryStore(db_manager),
            interval_seconds=args.interval_seconds,
            min_rows=args.min_rows,
            window_rows=args.window_rows,
            report_path=args.report_path,
            once=args.once,
        )
        if args.once:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        db_manager.engine.dispose()


if __name__ == "__main__":
    main()

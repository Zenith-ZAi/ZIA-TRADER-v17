#!/usr/bin/env python3
"""Rotula observações shadow com candles futuros e materializa padrões encerrados."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import Settings
from core.pattern_memory import PATTERN_FEATURES, PatternMemory
from database_manager import DatabaseManager


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--horizon-bars", type=int, default=3)
    parser.add_argument("--min-outcome-atr", type=float, default=None)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--output", default="data/shadow_label_summary.json")
    args = parser.parse_args()
    if args.horizon_bars <= 0:
        raise SystemExit("--horizon-bars precisa ser positivo")

    settings = Settings(
        DATABASE_URL=args.database_url or Settings().DATABASE_URL,
        PATTERN_MEMORY_ENABLED=True,
        PATTERN_MEMORY_MIN_OUTCOME_ATR=args.min_outcome_atr if args.min_outcome_atr is not None else Settings().PATTERN_MEMORY_MIN_OUTCOME_ATR,
    )
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    frame = pd.read_csv(args.dataset, parse_dates=["open_time"]).sort_values("open_time")
    frame = frame.drop_duplicates("open_time").set_index("open_time")
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    observations = db.get_unlabeled_ai_observations(limit=args.limit)
    memory = PatternMemory(db, settings)
    labeled = 0
    patterns = 0
    skipped = 0
    for observation in observations:
        observed_at = pd.Timestamp(observation.observed_at)
        if observed_at.tzinfo is None:
            observed_at = observed_at.tz_localize("UTC")
        else:
            observed_at = observed_at.tz_convert("UTC")
        position = close.index.searchsorted(observed_at, side="right") - 1
        future_position = position + args.horizon_bars
        if position < 0 or future_position >= len(close) or float(observation.price or 0.0) <= 0:
            skipped += 1
            continue
        current_price = float(observation.price)
        future_price = float(close.iloc[future_position])
        action = str(observation.action or observation.candidate_action or "hold").lower()
        direction = 1.0 if action == "buy" else -1.0 if action == "sell" else 0.0
        forward_return = (future_price / current_price - 1.0) * direction
        label = 1 if direction != 0 and forward_return > 0 else 0
        db.update_ai_observation_outcome(observation.id, forward_return, label)
        labeled += 1
        metadata = observation.metadata_json or {}
        signature = metadata.get("pattern_signature") if isinstance(metadata, dict) else None
        if action not in {"buy", "sell"} or not isinstance(signature, dict):
            continue
        atr_pct = max(float(signature.get("atr_pct", 0.0) or 0.0), 1e-9)
        outcome_atr = forward_return / atr_pct
        if outcome_atr >= memory.min_outcome_atr:
            normalized_signature = {name: float(signature.get(name, 0.0) or 0.0) for name in PATTERN_FEATURES}
            memory.record_completed_pattern(
                symbol=observation.symbol,
                signature=normalized_signature,
                entry_price=current_price,
                atr=current_price * atr_pct,
                outcome_atr=outcome_atr,
                outcome_label=label,
                strategy="pullback" if metadata.get("pullback_signal") else "market_signal",
                source_observation_id=observation.id,
                metadata={"horizon_bars": args.horizon_bars, "future_price": future_price},
            )
            patterns += 1

    summary = {
        "dataset_rows": int(len(frame)),
        "observations_seen": int(len(observations)),
        "observations_labeled": labeled,
        "observations_skipped": skipped,
        "patterns_materialized": patterns,
        "horizon_bars": args.horizon_bars,
        "min_outcome_atr": memory.min_outcome_atr,
        "orders_sent": 0,
        "note": "Somente observações com candles futuros disponíveis foram rotuladas; nenhuma ordem foi enviada.",
    }
    Path(args.output).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

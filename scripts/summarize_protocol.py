#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/binance_protocol_result.json")
    obj = json.loads(path.read_text(encoding="utf-8"))
    summary = {
        "rows": obj["dataset"]["rows"],
        "dataset": {k: obj["dataset"].get(k) for k in ["first_timestamp", "last_timestamp", "duplicates", "missing_values", "ohlcv_valid", "max_observed_gap_pct"]},
        "full": {k: obj["full_backtest"].get(k) for k in ["total_pnl", "return_pct", "sharpe_ratio", "max_drawdown", "trades_executed", "win_rate", "profit_factor", "total_fees", "blocked_event_bars", "blocked_event_candidates"]},
        "regimes": {k: {x: v.get(x) for x in ["status", "total_pnl", "sharpe_ratio", "max_drawdown", "trades_executed", "win_rate", "profit_factor"]} for k, v in obj["regimes"].items()},
        "gap": {"injections": obj["gap_stress"].get("injections", []), "metrics": {k: obj["gap_stress"].get("metrics", {}).get(k) for k in ["total_pnl", "sharpe_ratio", "max_drawdown", "trades_executed", "win_rate", "profit_factor"]}},
        "spoofing": obj["spoofing"],
        "tick_protocol": obj["tick_protocol"],
        "approval": obj["approval"],
        "elapsed_seconds": obj["elapsed_seconds"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

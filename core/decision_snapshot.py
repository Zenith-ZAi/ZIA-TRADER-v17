from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any


def _stable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _stable(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except Exception:
            return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def stable_hash(value: Any) -> str:
    encoded = json.dumps(_stable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_decision_snapshot(
    *,
    symbol: str,
    timeframe: str,
    mode: str,
    action: str,
    candidate_action: str,
    confidence: float,
    gate_status: str,
    before_context: dict[str, Any],
    observed_at: datetime | None = None,
    dataset_path: str | None = None,
    dataset_sha256: str | None = None,
    feature_context: Any = None,
) -> dict[str, Any]:
    observed = observed_at or datetime.now(timezone.utc)
    return {
        "snapshot_id": f"snap_{uuid.uuid4().hex}",
        "symbol": str(symbol),
        "timeframe": str(timeframe),
        "mode": str(mode),
        "observed_at": observed,
        "dataset_path": dataset_path,
        "dataset_sha256": dataset_sha256,
        "feature_hash": stable_hash(feature_context if feature_context is not None else {}),
        "action": str(action or "hold"),
        "candidate_action": str(candidate_action or "hold"),
        "confidence": float(confidence or 0.0),
        "gate_status": str(gate_status or "blocked"),
        "before_context": _stable(before_context),
    }

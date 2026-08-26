"""Smoke audit de importações de entrypoints e controles de segurança."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

modules = ["main", "worker", "security.rate_limiter", "execution.order_manager"]
results = []
for name in modules:
    try:
        importlib.import_module(name)
        results.append({"module": name, "ok": True})
    except Exception as exc:
        results.append({"module": name, "ok": False, "error_type": type(exc).__name__, "error": str(exc)})
print(json.dumps(results, ensure_ascii=False, indent=2))

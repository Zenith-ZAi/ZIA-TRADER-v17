"""Atualiza e valida a engenharia do core sem executar ordens."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str]) -> dict[str, object]:
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    return {
        "command": " ".join(command),
        "returncode": process.returncode,
        "stdout": process.stdout[-2000:],
        "stderr": process.stderr[-2000:],
        "ok": process.returncode == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-diagram", action="store_true")
    args = parser.parse_args()

    checks = [_run([sys.executable, "-m", "compileall", "-q", "core", "data", "execution", "config"])]
    if not args.skip_tests:
        checks.append(_run([sys.executable, "-m", "pytest", "-q"]))
    if not args.skip_diagram:
        checks.append(_run(["manus-render-diagram", "docs/core_refinement.mmd", "docs/core_refinement.png"]))
    summary = {
        "project": "ZIA-TRADER-v17",
        "orders_sent": 0,
        "live_trading_enabled": False,
        "checks": checks,
        "ok": all(bool(item["ok"]) for item in checks),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

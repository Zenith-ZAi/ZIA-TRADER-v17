"""Generate an engineering-gate snapshot from a source-controlled checklist.

This is a documentation metric, not production authorization or trading performance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_progress_snapshot(markdown: str, *, phase: str) -> dict:
    criteria = []
    for line in markdown.splitlines():
        if not re.match(r"^- \[", line):
            continue
        match = re.fullmatch(r"- \[([x ])\] (.+)", line)
        if match is None:
            raise ValueError("invalid_progress_criterion")
        label = match.group(2)
        criteria.append({"id": hashlib.sha256(label.encode()).hexdigest()[:12],
                         "accepted": match.group(1) == "x", "criterion": label})
    if not criteria:
        raise ValueError("progress_criteria_missing")
    if len({c["id"] for c in criteria}) != len(criteria):
        raise ValueError("duplicate_progress_criterion")
    accepted = sum(c["accepted"] for c in criteria)
    return {"schema_version": "engineering_gates_v1", "phase": phase,
            "metric": "accepted_checklist_gates_only_not_production_authorization",
            "criteria_sha256": hashlib.sha256("\n".join(c["criterion"] for c in criteria).encode()).hexdigest(),
            "accepted_gates": accepted, "total_gates": len(criteria),
            "progress_percent": round(100 * accepted / len(criteria), 2),
            "grants_live_authorization": False, "criteria": criteria}


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot de gates de engenharia; não libera trading.")
    parser.add_argument("--checklist", type=Path, default=ROOT / "docs/BACKEND_SANDBOX_GUIDE.md")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = build_progress_snapshot(args.checklist.read_text(), phase=args.phase)
    snapshot["observed_at"] = datetime.now(timezone.utc).isoformat()
    snapshot["checklist"] = str(args.checklist.relative_to(ROOT)) if args.checklist.is_relative_to(ROOT) else args.checklist.name
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    print(f"Gates aceitos: {snapshot['accepted_gates']}/{snapshot['total_gates']} ({snapshot['progress_percent']}%). Este snapshot não autoriza live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

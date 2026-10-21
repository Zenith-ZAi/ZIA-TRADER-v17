from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_dependency_lock_selects_cpu_torch_for_non_macos() -> None:
    lock_text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert re.search(
        r"(?m)^torch==[^\s\\]+\+cpu\s*;\s*sys_platform\s*!=\s*'darwin'",
        lock_text,
    ), "Linux/Windows runtime must use an explicit CPU-only Torch wheel."


def test_production_cpu_lock_excludes_cuda_wheels_and_is_hash_pinned() -> None:
    lock_text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    accelerator_packages = re.findall(
        r"(?mi)^(?:nvidia-[A-Za-z0-9_.-]+|cuda-[A-Za-z0-9_.-]+|triton)==",
        lock_text,
    )
    assert accelerator_packages == [], (
        "CPU VPS lock must not contain accelerator-only package pins: "
        f"{accelerator_packages}"
    )
    assert "--index-url https://pypi.org/simple" in lock_text
    assert "--hash=sha256:" in lock_text
    assert "/tmp/" not in lock_text


def test_constraints_file_is_not_the_install_manifest() -> None:
    constraints = (ROOT / "requirements.constraints.txt").read_text(encoding="utf-8")
    assert "do not install this file directly" in constraints.splitlines()[0]
    assert "nvidia-cusparselt-cu13" not in constraints

"""
Automated tests runner — runs all test suites with live progress and results.
"""
import time
import subprocess
from typing import Callable
from sqlalchemy.orm import Session

from cli.db_models import AdminUser
from cli.console import (
    console, header, success, error, warn, info,
    pause, menu, make_table, progress_bar,
)

# Test suite registry: (label, runner_fn)
_TEST_SUITES: list[tuple[str, str]] = [
    ("Banco", "tests/test_database_manager.py"),
    ("APIs", "tests/test_api.py"),
    ("Stress", "tests/test_stress.py"),
    ("Notícias", "tests/test_news_persistence.py"),
]


def run(db: Session, current_user: AdminUser) -> None:
    while True:
        opts = [(str(i + 1), label) for i, (label, _) in enumerate(_TEST_SUITES)]
        opts += [("11", "Executar Todos"), ("0", "Voltar")]
        choice = menu("TESTES", opts)
        if choice == "11":
            _run_all()
        elif choice == "0":
            break
        elif choice.isdigit() and 1 <= int(choice) <= len(_TEST_SUITES):
            label, path = _TEST_SUITES[int(choice) - 1]
            _run_suite(label, path)
        else:
            warn("Opção inválida.")


# ── test execution ────────────────────────────────────────────────────────────

def _run_suite(label: str, test_file: str | None) -> None:
    header(f"TESTE — {label}")
    _execute_test(label, test_file)
    pause()


def _run_all() -> None:
    header("EXECUTAR TODOS OS TESTES")
    results: list[tuple[str, bool, float, str]] = []

    t = make_table("Teste", "Status", "Tempo", "Detalhe", title="Resultados")

    pb = progress_bar("Executando testes…", len(_TEST_SUITES) * 20)
    with pb:
        task = pb.add_task("Testes", total=len(_TEST_SUITES) * 20)
        for label, path in _TEST_SUITES:
            pb.update(task, description=f"[cyan]{label}…[/cyan]")
            ok, elapsed, detail = _execute_test_silent(label, path)
            results.append((label, ok, elapsed, detail))
            for _ in range(20):
                time.sleep(0.04)
                pb.advance(task, 1)

    for label, ok, elapsed, detail in results:
        status = "[bold green]✔ OK[/bold green]" if ok else "[bold red]✖ Erro[/bold red]"
        t.add_row(label, status, f"{elapsed:.2f}s", detail[:60])

    console.print(t)

    passed = sum(1 for _, ok, _, _ in results if ok)
    total  = len(results)
    color  = "green" if passed == total else "yellow" if passed > 0 else "red"
    console.print(f"\n[bold {color}]{passed}/{total} suites passaram.[/bold {color}]")
    pause()


def _execute_test(label: str, test_file: str | None) -> tuple[bool, float, str]:
    start = time.time()
    pb = progress_bar(f"Executando {label}…", 100)
    with pb:
        task = pb.add_task(label, total=100)
        ok, detail = _run_pytest(test_file)
        for i in range(100):
            time.sleep(0.02)
            pb.advance(task, 1)
    elapsed = time.time() - start
    if ok:
        success(f"{label}: ✔ OK  ({elapsed:.2f}s)")
    else:
        error(f"{label}: ✖ Erro  ({elapsed:.2f}s)")
        if detail:
            console.print(f"[dim]{detail[:300]}[/dim]")
    return ok, elapsed, detail


def _execute_test_silent(label: str, test_file: str | None) -> tuple[bool, float, str]:
    start = time.time()
    ok, detail = _run_pytest(test_file)
    return ok, time.time() - start, detail


def _run_pytest(test_file: str | None) -> tuple[bool, str]:
    import os
    from pathlib import Path

    if test_file is None:
        return False, "Suíte sem arquivo de teste configurado"

    if not Path(test_file).exists():
        return False, f"Arquivo de teste não encontrado: {test_file}"

    result = subprocess.run(
        ["python", "-m", "pytest", test_file, "-v", "--tb=short", "-q"],
        capture_output=True, text=True, timeout=120,
    )
    ok = result.returncode == 0
    output = (result.stdout + result.stderr)[-400:]
    return ok, output

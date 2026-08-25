"""
Updates management — check versions, update deps, migrate DB, backup, rollback.
"""
import subprocess
import datetime
import shutil
import time
from pathlib import Path
from sqlalchemy.orm import Session
from rich.prompt import Prompt

from cli.db_models import AdminUser
from cli.console import (
    console, header, success, error, warn, info,
    pause, menu, confirm, progress_bar,
)

BACKUP_DIR = Path("data/backups")


def run(db: Session, current_user: AdminUser) -> None:
    while True:
        choice = menu("ATUALIZAÇÕES", [
            ("1", "Verificar Novas Versões"),
            ("2", "Atualizar Dependências"),
            ("3", "Migrar Banco de Dados"),
            ("4", "Executar Scripts de Manutenção"),
            ("5", "Atualizar e validar Core"),
            ("6", "Backup Automático"),
            ("7", "Rollback"),
            ("0", "Voltar"),
        ])
        if choice == "1":
            _check_versions(current_user)
        elif choice == "2":
            _update_deps(current_user)
        elif choice == "3":
            _migrate_db(db, current_user)
        elif choice == "4":
            _run_scripts(current_user)
        elif choice == "5":
            _update_core(current_user)
        elif choice == "6":
            _backup(db, current_user)
        elif choice == "7":
            _rollback(current_user)
        elif choice == "0":
            break
        else:
            warn("Opção inválida.")


# ── helpers ──────────────────────────────────────────────────────────────────

def _check_admin(user: AdminUser) -> bool:
    if user.role != "admin":
        error("Apenas administradores podem executar esta ação.")
        return False
    return True


def _check_versions(user: AdminUser) -> None:
    if not _check_admin(user):
        return
    header("VERIFICAR VERSÕES")
    pb = progress_bar("Verificando dependências…", 100)
    with pb:
        task = pb.add_task("Verificando", total=100)
        result = subprocess.run(
            ["pip", "list", "--outdated", "--format=columns"],
            capture_output=True, text=True
        )
        for i in range(100):
            time.sleep(0.02)
            pb.advance(task, 1)

    if result.returncode == 0 and result.stdout.strip():
        lines = result.stdout.strip().splitlines()
        from cli.console import make_table
        t = make_table("Pacote", "Versão Atual", "Nova Versão", title="Pacotes Desatualizados")
        for line in lines[2:]:   # skip header lines
            parts = line.split()
            if len(parts) >= 3:
                t.add_row(parts[0], parts[1], parts[2])
        console.print(t)
    else:
        success("Todas as dependências estão atualizadas.")
    pause()


def _update_deps(user: AdminUser) -> None:
    if not _check_admin(user):
        return
    if not confirm("Atualizar dependências? O servidor precisará ser reiniciado."):
        return
    header("ATUALIZANDO DEPENDÊNCIAS")
    pb = progress_bar("Atualizando…", 100)
    with pb:
        task = pb.add_task("Pip upgrade", total=100)
        proc = subprocess.Popen(
            ["pip", "install", "--upgrade", "-r", "requirements.txt"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        lines_done = 0
        while True:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            pb.update(task, description=f"[cyan]{line.strip()[:60]}[/cyan]")
            lines_done += 1
            pb.advance(task, min(2, 100 - lines_done))
        pb.update(task, completed=100)
    if proc.returncode == 0:
        success("Dependências atualizadas com sucesso.")
    else:
        error("Falha ao atualizar dependências — verifique os logs.")
    pause()


def _migrate_db(db: Session, user: AdminUser) -> None:
    if not _check_admin(user):
        return
    if not confirm("Executar migrações do banco de dados?"):
        return
    header("MIGRAR BANCO DE DADOS")
    pb = progress_bar("Migrando…", 60)
    with pb:
        task = pb.add_task("Migração", total=60)
        # Re-create all tables (safe: create_all is idempotent)
        from database import Base
        from cli.db_models import AdminUser as AU  # noqa: ensure model imported
        from sqlalchemy.orm import Session as S
        engine = db.bind
        if engine is None:
            engine = db.get_bind()
        for i in range(40):
            time.sleep(0.03)
            pb.advance(task, 1)
        Base.metadata.create_all(engine)
        for i in range(20):
            time.sleep(0.03)
            pb.advance(task, 1)
    success("Banco de dados migrado com sucesso.")
    pause()


def _run_scripts(user: AdminUser) -> None:
    if not _check_admin(user):
        return
    header("SCRIPTS DE MANUTENÇÃO")
    scripts = list(Path("scripts").glob("*.py")) if Path("scripts").exists() else []
    if not scripts:
        info("Nenhum script encontrado em scripts/")
        pause()
        return
    for i, s in enumerate(scripts, 1):
        console.print(f"  [cyan][{i}][/cyan]  {s.name}")
    idx = Prompt.ask("Script a executar (0=cancelar)").strip()
    if idx == "0" or not idx.isdigit():
        return
    script = scripts[int(idx) - 1]
    pb = progress_bar(f"Executando {script.name}", 100)
    with pb:
        task = pb.add_task(script.name, total=100)
        result = subprocess.run(["python", str(script)], capture_output=True, text=True)
        for i in range(100):
            time.sleep(0.02)
            pb.advance(task, 1)
    if result.returncode == 0:
        success(f"Script '{script.name}' concluído.")
        if result.stdout:
            console.print(result.stdout[-500:])
    else:
        error(f"Script falhou:\n{result.stderr[-300:]}")
    pause()


def _update_core(user: AdminUser) -> None:
    if not _check_admin(user):
        return
    if not confirm("Executar compilação, testes e atualização do diagrama do core?"):
        return
    header("ATUALIZAR E VALIDAR CORE")
    result = subprocess.run(
        ["python", "scripts/update_core.py"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        success("Core atualizado e validado sem envio de ordens.")
    else:
        error("A validação do core falhou; verifique a saída abaixo.")
    if result.stdout:
        console.print(result.stdout[-4000:])
    if result.stderr:
        console.print(result.stderr[-1000:])
    pause()


def _backup(db: Session, user: AdminUser) -> None:
    if not _check_admin(user):
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    header("BACKUP")
    pb = progress_bar("Criando backup…", 100)
    with pb:
        task = pb.add_task("Backup", total=100)
        # Backup .env
        if Path(".env").exists():
            shutil.copy(".env", BACKUP_DIR / f"env_{ts}.bak")
        for i in range(50):
            time.sleep(0.02)
            pb.advance(task, 1)
        # Backup SQLite db if present
        sqlite_db = Path("data/zia_trader.db")
        if sqlite_db.exists():
            shutil.copy(sqlite_db, BACKUP_DIR / f"zia_trader_{ts}.db")
        for i in range(50):
            time.sleep(0.02)
            pb.advance(task, 1)
    success(f"Backup criado em {BACKUP_DIR}/")
    pause()


def _rollback(user: AdminUser) -> None:
    if not _check_admin(user):
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = sorted(BACKUP_DIR.glob("*.db"), reverse=True)
    if not backups:
        warn("Nenhum backup disponível.")
        pause()
        return
    header("ROLLBACK")
    for i, b in enumerate(backups[:10], 1):
        console.print(f"  [cyan][{i}][/cyan]  {b.name}")
    idx = Prompt.ask("Backup a restaurar (0=cancelar)").strip()
    if idx == "0" or not idx.isdigit() or int(idx) > len(backups):
        info("Operação cancelada.")
        pause()
        return
    backup_file = backups[int(idx) - 1]
    if confirm(f"Restaurar '{backup_file.name}'? Isso sobrescreverá o banco atual."):
        shutil.copy(backup_file, "data/zia_trader.db")
        success(f"Banco restaurado de '{backup_file.name}'.")
    else:
        info("Rollback cancelado.")
    pause()

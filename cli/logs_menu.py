"""
Logs viewer — view, filter, and export system logs.
"""
import csv
import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from rich.prompt import Prompt

from database import SystemLog
from cli.db_models import AdminUser
from cli.console import (
    console, header, success, error, warn, info,
    pause, menu, confirm, make_table,
)

LOG_CATEGORIES = {
    "1":  ("Operações",     None),
    "2":  ("Erros",         "ERROR"),
    "3":  ("Autenticação",  "auth"),
    "4":  ("IA",            "ai"),
    "5":  ("Treinamentos",  "training"),
    "6":  ("Exchange",      "exchange"),
    "7":  ("API",           "api"),
    "8":  ("Banco",         "database"),
    "9":  ("Segurança",     "security"),
    "10": ("Todos",         None),
}


def run(db: Session, current_user: AdminUser) -> None:
    while True:
        choice = menu("LOGS", [
            ("1",  "Operações"),
            ("2",  "Erros"),
            ("3",  "Autenticação"),
            ("4",  "IA"),
            ("5",  "Treinamentos"),
            ("6",  "Exchange"),
            ("7",  "API"),
            ("8",  "Banco"),
            ("9",  "Segurança"),
            ("10", "Todos"),
            ("11", "Exportar Logs"),
            ("12", "Limpar Logs Antigos"),
            ("0",  "Voltar"),
        ])
        if choice in LOG_CATEGORIES:
            label, filter_val = LOG_CATEGORIES[choice]
            _show_logs(db, label, filter_val)
        elif choice == "11":
            _export(db)
        elif choice == "12":
            _clean(db, current_user)
        elif choice == "0":
            break
        else:
            warn("Opção inválida.")


# ── helpers ──────────────────────────────────────────────────────────────────

def _show_logs(db: Session, category: str, filter_val: str | None) -> None:
    header(f"LOGS — {category}")
    limit_str = Prompt.ask("Quantos registros exibir?", default="50").strip()
    limit = int(limit_str) if limit_str.isdigit() else 50

    q = db.query(SystemLog).order_by(SystemLog.timestamp.desc())
    if filter_val:
        if filter_val == "ERROR":
            q = q.filter(SystemLog.level == "ERROR")
        else:
            q = q.filter(SystemLog.module.ilike(f"%{filter_val}%"))
    logs = q.limit(limit).all()

    if not logs:
        info("Nenhum registro encontrado.")
        pause()
        return

    t = make_table("Timestamp", "Nível", "Módulo", "Mensagem", title=category)
    level_colors = {"ERROR": "red", "WARNING": "yellow", "INFO": "green", "DEBUG": "dim"}
    for log in logs:
        color = level_colors.get(log.level, "white")
        ts = log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "—"
        msg = (log.message or "")[:80]
        t.add_row(ts, f"[{color}]{log.level}[/{color}]",
                  log.module or "—", msg)
    console.print(t)
    pause()


def _export(db: Session) -> None:
    header("EXPORTAR LOGS")
    out_dir = Path("data/exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = out_dir / f"logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    logs = db.query(SystemLog).order_by(SystemLog.timestamp.desc()).limit(10000).all()
    if not logs:
        warn("Nenhum log para exportar.")
        pause()
        return

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "level", "module", "account_id", "message"])
        for log in logs:
            writer.writerow([
                log.timestamp, log.level, log.module,
                log.account_id or "", log.message or "",
            ])
    success(f"Logs exportados para: {filename}")
    pause()


def _clean(db: Session, user: AdminUser) -> None:
    if user.role != "admin":
        error("Apenas administradores podem limpar logs.")
        return
    days_str = Prompt.ask("Excluir logs com mais de quantos dias?", default="30").strip()
    if not days_str.isdigit():
        error("Valor inválido.")
        pause()
        return
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=int(days_str))
    if confirm(f"Excluir logs anteriores a {cutoff.date()}?"):
        deleted = db.query(SystemLog).filter(SystemLog.timestamp < cutoff).delete()
        db.commit()
        success(f"{deleted} registro(s) removido(s).")
    else:
        info("Operação cancelada.")
    pause()

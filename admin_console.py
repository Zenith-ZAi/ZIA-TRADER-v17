"""
ZIA Trader — Admin Console entry point.

Usage:
    python admin_console.py
"""
import sys
import logging
import argparse

# ── suppress noisy library logs in the console UI ────────────────────────────
logging.basicConfig(level=logging.ERROR)
for noisy in ("sqlalchemy", "passlib", "urllib3", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from config.settings import settings
from database import Base
from cli.db_models import AdminUser, ExchangeConfig, StrategyConfig, AlgorithmConfig  # noqa: register models

# ── DB setup ──────────────────────────────────────────────────────────────────
_engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)
Base.metadata.create_all(_engine)          # idempotent — creates CLI tables if missing
_Session = sessionmaker(bind=_engine)


def get_db() -> Session:
    return _Session()


# ── menu modules ──────────────────────────────────────────────────────────────
from cli.auth           import login
from cli.console        import console, banner, divider, menu, warn, success, info
from cli.security_menu  import register_session, revoke_session
import cli.exchange_menu    as exchange_menu
import cli.users_menu       as users_menu
import cli.strategies_menu  as strategies_menu
import cli.algorithms_menu  as algorithms_menu
import cli.ai_menu          as ai_menu
import cli.config_menu      as config_menu
import cli.logs_menu        as logs_menu
import cli.updates_menu     as updates_menu
import cli.security_menu    as security_menu
import cli.tests_menu       as tests_menu
import cli.runtime_menu      as runtime_menu


# ── main loop ────────────────────────────────────────────────────────────────

def main(mode: str | None = None) -> None:
    if mode:
        settings.ORDER_MANAGER_MODE = mode
        settings.ORDER_CONFIRMATION_REQUIRED = True
    db = get_db()

    # ── authentication ────────────────────────────────────────────────────
    current_user = login(db)
    if not current_user:
        console.print("[red]Acesso negado.[/red]")
        sys.exit(1)

    register_session(current_user.username)

    # ── main dashboard ────────────────────────────────────────────────────
    while True:
        choice = menu("MENU PRINCIPAL", [
            ("1",  "Exchange APIs"),
            ("2",  "Usuários"),
            ("3",  "Estratégias"),
            ("4",  "IA"),
            ("5",  "Algoritmos"),
            ("6",  "Configurações"),
            ("7",  "Logs"),
            ("8",  "Atualizações"),
            ("9",  "Segurança"),
            ("10", "Testes"),
            ("11", "Trading Híbrido"),
            ("0",  "Sair"),
        ])

        if choice == "1":
            exchange_menu.run(db, current_user)
        elif choice == "2":
            users_menu.run(db, current_user)
        elif choice == "3":
            strategies_menu.run(db, current_user)
        elif choice == "4":
            ai_menu.run(db, current_user)
        elif choice == "5":
            algorithms_menu.run(db, current_user)
        elif choice == "6":
            config_menu.run(db, current_user)
        elif choice == "7":
            logs_menu.run(db, current_user)
        elif choice == "8":
            updates_menu.run(db, current_user)
        elif choice == "9":
            security_menu.run(db, current_user)
        elif choice == "10":
            tests_menu.run(db, current_user)
        elif choice == "11":
            runtime_menu.run(db, current_user)
        elif choice == "0":
            revoke_session(current_user.username)
            console.print("\n[bold cyan]Encerrando sessão. Até logo![/bold cyan]\n")
            db.close()
            sys.exit(0)
        else:
            warn("Opção inválida. Digite um número do menu.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Console administrativo ZIA Trader")
    parser.add_argument("--mode", choices=("manual", "auto"), default=None, help="modo do OrderManager")
    main(parser.parse_args().mode)

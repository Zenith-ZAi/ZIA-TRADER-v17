"""
Exchange APIs management — add, edit, delete, activate, deactivate, view.
"""
import getpass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from rich.prompt import Prompt

from cli.db_models import AdminUser, ExchangeConfig
from cli.crypto_utils import encrypt, decrypt, mask
from cli.console import (
    console, header, success, error, warn, info,
    divider, pause, menu, confirm, make_table,
)

KNOWN_EXCHANGES = ["Binance", "Bybit", "OKX", "KuCoin", "Bitget", "Gate.io", "Outro"]


def run(db: Session, current_user: AdminUser) -> None:
    while True:
        choice = menu("EXCHANGE APIs", [
            ("1", "Adicionar Exchange"),
            ("2", "Editar Exchange"),
            ("3", "Excluir Exchange"),
            ("4", "Ativar / Desativar"),
            ("5", "Visualizar Exchanges"),
            ("0", "Voltar"),
        ])
        if choice == "1":
            _add(db, current_user)
        elif choice == "2":
            _edit(db, current_user)
        elif choice == "3":
            _delete(db, current_user)
        elif choice == "4":
            _toggle(db, current_user)
        elif choice == "5":
            _list(db)
        elif choice == "0":
            break
        else:
            warn("Opção inválida.")


# ── helpers ──────────────────────────────────────────────────────────────────

def _require_admin(user: AdminUser) -> bool:
    if user.role not in ("admin", "operator"):
        error("Permissão negada.")
        return False
    return True


def _pick_exchange(db: Session, prompt_msg: str = "ID da Exchange") -> Optional[ExchangeConfig]:
    _list(db)
    raw = Prompt.ask(prompt_msg).strip()
    if not raw.isdigit():
        error("ID inválido.")
        return None
    exc = db.query(ExchangeConfig).filter_by(id=int(raw)).first()
    if not exc:
        error("Exchange não encontrada.")
    return exc


def _list(db: Session) -> None:
    exchanges = db.query(ExchangeConfig).order_by(ExchangeConfig.id).all()
    t = make_table("ID", "Nome", "Conta", "Modo", "Status", "API Key", "Cadastro",
                   title="Exchanges Cadastradas")
    for e in exchanges:
        mode   = "[yellow]Testnet[/yellow]" if e.testnet    else "[green]Produção[/green]"
        status = "[green]Ativo[/green]"     if e.is_active  else "[red]Inativo[/red]"
        api    = mask(decrypt(e.api_key_encrypted)) if e.api_key_encrypted else "—"
        t.add_row(str(e.id), e.name, e.account_name or "—", mode, status, api,
                  e.created_at.strftime("%Y-%m-%d") if e.created_at else "—")
    console.print(t)
    if not exchanges:
        info("Nenhuma exchange cadastrada.")
    pause()


def _add(db: Session, user: AdminUser) -> None:
    if not _require_admin(user):
        return

    header("ADICIONAR EXCHANGE")
    for i, ex in enumerate(KNOWN_EXCHANGES, 1):
        console.print(f"  [cyan][{i}][/cyan]  {ex}")
    idx = Prompt.ask("Exchange").strip()
    if idx.isdigit() and 1 <= int(idx) <= len(KNOWN_EXCHANGES):
        name = KNOWN_EXCHANGES[int(idx) - 1]
        if name == "Outro":
            name = Prompt.ask("Nome da exchange").strip()
    else:
        name = idx

    api_key    = getpass.getpass("API Key: ")
    secret_key = getpass.getpass("Secret Key: ")
    passphrase = getpass.getpass("Passphrase (deixe vazio se não aplicável): ")

    account_name = Prompt.ask("Nome da conta", default="principal")
    description  = Prompt.ask("Descrição", default="")
    testnet_raw  = Prompt.ask("Modo Testnet? (s/n)", default="s").strip().lower()
    testnet      = testnet_raw in ("s", "sim", "y", "yes")

    exc = ExchangeConfig(
        name=name,
        api_key_encrypted=encrypt(api_key),
        secret_key_encrypted=encrypt(secret_key),
        passphrase_encrypted=encrypt(passphrase) if passphrase else "",
        account_name=account_name,
        description=description,
        testnet=testnet,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(exc)
    db.commit()
    success(f"Exchange '{name}' adicionada (ID {exc.id}).")
    pause()


def _edit(db: Session, user: AdminUser) -> None:
    if not _require_admin(user):
        return
    exc = _pick_exchange(db, "ID da exchange a editar")
    if not exc:
        return

    header(f"EDITAR — {exc.name}")
    console.print("[dim]Deixe em branco para manter o valor atual.[/dim]")

    account_name = Prompt.ask("Nome da conta",  default=exc.account_name or "").strip()
    description  = Prompt.ask("Descrição",       default=exc.description  or "").strip()
    testnet_raw  = Prompt.ask("Testnet? (s/n)",  default="s" if exc.testnet else "n").strip().lower()
    exc.testnet      = testnet_raw in ("s", "sim", "y", "yes")
    exc.account_name = account_name
    exc.description  = description

    if confirm("Atualizar API Key?"):
        exc.api_key_encrypted    = encrypt(getpass.getpass("Nova API Key: "))
        exc.secret_key_encrypted = encrypt(getpass.getpass("Nova Secret Key: "))
        exc.passphrase_encrypted = encrypt(getpass.getpass("Nova Passphrase (vazio=nenhuma): "))

    db.commit()
    success("Exchange atualizada.")
    pause()


def _delete(db: Session, user: AdminUser) -> None:
    if user.role != "admin":
        error("Apenas administradores podem excluir exchanges.")
        return
    exc = _pick_exchange(db, "ID da exchange a excluir")
    if not exc:
        return
    if confirm(f"Excluir '{exc.name}'? Esta ação é irreversível."):
        db.delete(exc)
        db.commit()
        success("Exchange excluída.")
    else:
        info("Operação cancelada.")
    pause()


def _toggle(db: Session, user: AdminUser) -> None:
    if not _require_admin(user):
        return
    exc = _pick_exchange(db, "ID da exchange a ativar/desativar")
    if not exc:
        return
    exc.is_active = not exc.is_active
    db.commit()
    state = "[green]ativada[/green]" if exc.is_active else "[red]desativada[/red]"
    success(f"Exchange '{exc.name}' {state}.")
    pause()

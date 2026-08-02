"""
Users management — create, edit, delete, block, unblock, change password.
"""
import getpass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from rich.prompt import Prompt

from cli.db_models import AdminUser
from cli.auth import hash_password
from cli.console import (
    console, header, success, error, warn, info,
    divider, pause, menu, confirm, make_table, ROLES,
)

ROLE_LABELS = {
    "admin":    "Administrador",
    "operator": "Operador",
    "reader":   "Leitura",
    "guest":    "Convidado",
}


def run(db: Session, current_user: AdminUser) -> None:
    while True:
        choice = menu("USUÁRIOS", [
            ("1", "Criar Usuário"),
            ("2", "Alterar Senha"),
            ("3", "Alterar Papel / Permissão"),
            ("4", "Bloquear Usuário"),
            ("5", "Desbloquear Usuário"),
            ("6", "Excluir Usuário"),
            ("7", "Listar Usuários"),
            ("0", "Voltar"),
        ])
        if choice == "1":
            _create(db, current_user)
        elif choice == "2":
            _change_password(db, current_user)
        elif choice == "3":
            _change_role(db, current_user)
        elif choice == "4":
            _block(db, current_user, block=True)
        elif choice == "5":
            _block(db, current_user, block=False)
        elif choice == "6":
            _delete(db, current_user)
        elif choice == "7":
            _list(db)
        elif choice == "0":
            break
        else:
            warn("Opção inválida.")


# ── helpers ──────────────────────────────────────────────────────────────────

def _list(db: Session) -> None:
    users = db.query(AdminUser).order_by(AdminUser.id).all()
    t = make_table("ID", "Usuário", "Papel", "Status", "Último Login", title="Usuários")
    for u in users:
        status    = "[red]Bloqueado[/red]" if u.is_blocked else "[green]Ativo[/green]"
        last_login = u.last_login.strftime("%Y-%m-%d %H:%M") if u.last_login else "—"
        t.add_row(str(u.id), u.username, ROLE_LABELS.get(u.role, u.role), status, last_login)
    console.print(t)
    if not users:
        info("Nenhum usuário cadastrado.")
    pause()


def _pick_user(db: Session, prompt_msg: str = "ID do usuário") -> Optional[AdminUser]:
    _list(db)
    raw = Prompt.ask(prompt_msg).strip()
    if not raw.isdigit():
        error("ID inválido.")
        return None
    user = db.query(AdminUser).filter_by(id=int(raw)).first()
    if not user:
        error("Usuário não encontrado.")
    return user


def _create(db: Session, current_user: AdminUser) -> None:
    if current_user.role != "admin":
        error("Apenas administradores podem criar usuários.")
        return

    header("CRIAR USUÁRIO")
    username = Prompt.ask("Nome de usuário").strip()
    if db.query(AdminUser).filter_by(username=username).first():
        error(f"Usuário '{username}' já existe.")
        pause()
        return

    password = getpass.getpass("Senha: ")
    confirm_pwd = getpass.getpass("Confirmar senha: ")
    if password != confirm_pwd:
        error("As senhas não coincidem.")
        pause()
        return
    if len(password) < 8:
        error("A senha deve ter pelo menos 8 caracteres.")
        pause()
        return

    console.print("Papéis disponíveis:")
    for i, (role, label) in enumerate(ROLE_LABELS.items(), 1):
        console.print(f"  [cyan][{i}][/cyan]  {label} ({role})")
    role_idx = Prompt.ask("Papel", default="2").strip()
    roles = list(ROLE_LABELS.keys())
    role = roles[int(role_idx) - 1] if role_idx.isdigit() and 1 <= int(role_idx) <= len(roles) else "operator"

    user = AdminUser(
        username=username,
        password_hash=hash_password(password),
        role=role,
        must_change_pwd=True,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    success(f"Usuário '{username}' criado com papel '{ROLE_LABELS[role]}'.")
    pause()


def _change_password(db: Session, current_user: AdminUser) -> None:
    header("ALTERAR SENHA")
    # Admins can change any user; others only their own
    if current_user.role == "admin":
        target = _pick_user(db, "ID do usuário (Enter para si mesmo)")
        if not target:
            target = current_user
    else:
        target = current_user

    if target.id != current_user.id:
        if current_user.role != "admin":
            error("Sem permissão.")
            return
    else:
        old_pwd = getpass.getpass("Senha atual: ")
        from cli.auth import verify_password
        if not verify_password(old_pwd, target.password_hash):
            error("Senha atual incorreta.")
            pause()
            return

    new_pwd = getpass.getpass("Nova senha: ")
    confirm_pwd = getpass.getpass("Confirmar nova senha: ")
    if new_pwd != confirm_pwd:
        error("As senhas não coincidem.")
        pause()
        return
    if len(new_pwd) < 8:
        error("A senha deve ter pelo menos 8 caracteres.")
        pause()
        return

    target.password_hash   = hash_password(new_pwd)
    target.must_change_pwd = False
    db.commit()
    success("Senha alterada com sucesso.")
    pause()


def _change_role(db: Session, current_user: AdminUser) -> None:
    if current_user.role != "admin":
        error("Apenas administradores podem alterar papéis.")
        return
    target = _pick_user(db, "ID do usuário")
    if not target:
        return
    console.print("Papéis disponíveis:")
    roles = list(ROLE_LABELS.keys())
    for i, (r, label) in enumerate(ROLE_LABELS.items(), 1):
        console.print(f"  [cyan][{i}][/cyan]  {label}")
    idx = Prompt.ask("Novo papel").strip()
    if idx.isdigit() and 1 <= int(idx) <= len(roles):
        target.role = roles[int(idx) - 1]
        db.commit()
        success(f"Papel de '{target.username}' alterado para '{ROLE_LABELS[target.role]}'.")
    else:
        error("Opção inválida.")
    pause()


def _block(db: Session, current_user: AdminUser, block: bool) -> None:
    if current_user.role != "admin":
        error("Apenas administradores podem bloquear/desbloquear usuários.")
        return
    action = "bloquear" if block else "desbloquear"
    target = _pick_user(db, f"ID do usuário a {action}")
    if not target:
        return
    if target.id == current_user.id:
        error("Você não pode bloquear a si mesmo.")
        pause()
        return
    target.is_blocked      = block
    target.failed_attempts = 0
    db.commit()
    state = "[red]bloqueado[/red]" if block else "[green]desbloqueado[/green]"
    success(f"Usuário '{target.username}' {state}.")
    pause()


def _delete(db: Session, current_user: AdminUser) -> None:
    if current_user.role != "admin":
        error("Apenas administradores podem excluir usuários.")
        return
    target = _pick_user(db, "ID do usuário a excluir")
    if not target:
        return
    if target.id == current_user.id:
        error("Você não pode excluir a si mesmo.")
        pause()
        return
    if confirm(f"Excluir usuário '{target.username}'? Esta ação é irreversível."):
        db.delete(target)
        db.commit()
        success(f"Usuário '{target.username}' excluído.")
    else:
        info("Operação cancelada.")
    pause()

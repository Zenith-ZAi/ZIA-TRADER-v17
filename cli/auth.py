"""
Authentication for the Admin CLI — secure login with getpass + bcrypt.
"""
import getpass
import logging
from datetime import datetime
from typing import Optional

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from cli.db_models import AdminUser
from cli.console import console, banner, success, error, warn, divider

logger = logging.getLogger(__name__)
pwd_ctx = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

ROLES = {
    "admin":    "Administrador",
    "operator": "Operador",
    "reader":   "Leitura",
    "guest":    "Convidado",
}


# ── helpers ──────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


def seed_default_admin(db: Session) -> None:
    """Create a default 'admin' user if no admin exists yet."""
    if not db.query(AdminUser).filter_by(role="admin").first():
        user = AdminUser(
            username="admin",
            password_hash=hash_password("admin123"),
            role="admin",
            must_change_pwd=True,
        )
        db.add(user)
        db.commit()
        warn("Usuário padrão criado: admin / admin123  — [bold]troque a senha imediatamente[/bold]")


# ── login flow ────────────────────────────────────────────────────────────────

def login(db: Session) -> Optional[AdminUser]:
    """
    Prompt for credentials, enforce rate-limiting, return the authenticated
    AdminUser or None on failure.
    """
    seed_default_admin(db)

    console.print()
    banner()
    divider()

    username = console.input("[bold white]Usuário:[/bold white] ").strip()
    password = getpass.getpass("Senha: ")

    user: Optional[AdminUser] = db.query(AdminUser).filter_by(username=username).first()

    if not user:
        error("Usuário inválido.")
        _log_auth_failure(db, username, "usuário não encontrado")
        return None

    if user.is_blocked:
        error("Conta bloqueada. Contate um administrador.")
        _log_auth_failure(db, username, "conta bloqueada")
        return None

    if not verify_password(password, user.password_hash):
        user.failed_attempts = (user.failed_attempts or 0) + 1
        if user.failed_attempts >= 5:
            user.is_blocked = True
            error("Muitas tentativas incorretas — conta bloqueada.")
        else:
            error("Usuário inválido.")
        db.commit()
        _log_auth_failure(db, username, "senha incorreta")
        return None

    # Success
    user.failed_attempts = 0
    user.last_login = datetime.utcnow()
    db.commit()

    success(f"Autenticado com sucesso.  [dim]Papel: {ROLES.get(user.role, user.role)}[/dim]")

    if user.must_change_pwd:
        warn("Você deve alterar sua senha agora.")
        _force_change_password(db, user)

    return user


def _force_change_password(db: Session, user: AdminUser) -> None:
    while True:
        new_pwd  = getpass.getpass("Nova senha: ")
        confirm  = getpass.getpass("Confirmar nova senha: ")
        if new_pwd != confirm:
            error("As senhas não coincidem. Tente novamente.")
            continue
        if len(new_pwd) < 8:
            error("A senha deve ter pelo menos 8 caracteres.")
            continue
        user.password_hash   = hash_password(new_pwd)
        user.must_change_pwd = False
        db.commit()
        success("Senha alterada com sucesso.")
        return


def _log_auth_failure(db: Session, username: str, reason: str) -> None:
    try:
        from database import SystemLog
        log = SystemLog(
            level="WARNING",
            message=f"Falha de autenticação CLI para '{username}': {reason}",
            module="cli.auth",
        )
        db.add(log)
        db.commit()
    except Exception:
        pass

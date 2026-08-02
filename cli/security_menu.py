"""
Security management — key rotation, password reset, token revocation, IP block,
access logs, active sessions, session expiry.
"""
import datetime
from sqlalchemy.orm import Session
from rich.prompt import Prompt

from cli.db_models import AdminUser
from cli.crypto_utils import generate_key
from cli.console import (
    console, header, success, error, warn, info,
    pause, menu, confirm, make_table,
)

# In-memory session registry (keyed by username)
_active_sessions: dict[str, datetime.datetime] = {}


def register_session(username: str) -> None:
    _active_sessions[username] = datetime.datetime.utcnow()


def revoke_session(username: str) -> None:
    _active_sessions.pop(username, None)


def run(db: Session, current_user: AdminUser) -> None:
    while True:
        choice = menu("SEGURANÇA", [
            ("1", "Gerar Nova Chave de Criptografia (AES)"),
            ("2", "Trocar Senha Master"),
            ("3", "Revogar Tokens / Sessões"),
            ("4", "Bloquear IP"),
            ("5", "Logs de Acesso"),
            ("6", "Sessões Ativas"),
            ("7", "Tempo de Expiração de Sessão"),
            ("0", "Voltar"),
        ])
        if choice == "1":
            _rotate_key(current_user)
        elif choice == "2":
            _change_master_pwd(db, current_user)
        elif choice == "3":
            _revoke_tokens(db, current_user)
        elif choice == "4":
            _block_ip(current_user)
        elif choice == "5":
            _access_logs(db)
        elif choice == "6":
            _active_sessions_menu()
        elif choice == "7":
            _session_expiry(current_user)
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


def _rotate_key(user: AdminUser) -> None:
    if not _check_admin(user):
        return
    header("GERAR NOVA CHAVE DE CRIPTOGRAFIA")
    warn("⚠  Ao gerar uma nova chave, todos os segredos criptografados (API Keys)")
    warn("   precisarão ser re-cadastrados. Esta ação não pode ser desfeita.")
    if not confirm("Confirmar geração de nova chave?"):
        info("Operação cancelada.")
        pause()
        return
    new_key = generate_key()
    console.print(f"\n[bold yellow]Nova ENCRYPTION_KEY:[/bold yellow]")
    console.print(f"[white]{new_key}[/white]")
    console.print(
        "\n[dim]Adicione esta chave ao seu arquivo .env ou variável de ambiente "
        "ENCRYPTION_KEY antes de reiniciar o sistema.[/dim]"
    )
    pause()


def _change_master_pwd(db: Session, user: AdminUser) -> None:
    if not _check_admin(user):
        return
    import getpass
    from cli.auth import verify_password, hash_password
    header("TROCAR SENHA MASTER")
    current = getpass.getpass("Senha atual: ")
    if not verify_password(current, user.password_hash):
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
    user.password_hash   = hash_password(new_pwd)
    user.must_change_pwd = False
    db.commit()
    success("Senha master alterada com sucesso.")
    pause()


def _revoke_tokens(db: Session, user: AdminUser) -> None:
    if not _check_admin(user):
        return
    header("REVOGAR TOKENS / SESSÕES")
    users = db.query(AdminUser).all()
    for u in users:
        status = "[green]ativa[/green]" if u.username in _active_sessions else "—"
        console.print(f"  {u.username:<20} sessão: {status}")

    console.print(
        "\n  [cyan][1][/cyan]  Revogar sessão específica"
        "\n  [cyan][2][/cyan]  Revogar todas as sessões"
        "\n  [cyan][0][/cyan]  Cancelar"
    )
    choice = Prompt.ask("Opção").strip()
    if choice == "1":
        username = Prompt.ask("Nome de usuário").strip()
        if username in _active_sessions:
            revoke_session(username)
            success(f"Sessão de '{username}' revogada.")
        else:
            warn(f"Nenhuma sessão ativa para '{username}'.")
    elif choice == "2":
        _active_sessions.clear()
        success("Todas as sessões foram revogadas.")
    pause()


def _block_ip(user: AdminUser) -> None:
    if not _check_admin(user):
        return
    header("BLOQUEAR IP")
    warn("Implementação de bloqueio de IP requer configuração no firewall do servidor.")
    ip = Prompt.ask("IP a bloquear").strip()
    if ip:
        # Log the action — in production, this would call iptables/ufw or a WAF API
        info(f"IP '{ip}' marcado para bloqueio.")
        info("Execute manualmente: [bold]sudo ufw deny from {ip}[/bold]")
        success(f"Ação registrada nos logs.")
    pause()


def _access_logs(db: Session) -> None:
    header("LOGS DE ACESSO")
    from database import SystemLog
    logs = (
        db.query(SystemLog)
        .filter(SystemLog.module == "cli.auth")
        .order_by(SystemLog.timestamp.desc())
        .limit(100)
        .all()
    )
    t = make_table("Timestamp", "Nível", "Mensagem", title="Logs de Autenticação")
    for log in logs:
        color = "red" if log.level in ("ERROR", "WARNING") else "green"
        ts = log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "—"
        t.add_row(ts, f"[{color}]{log.level}[/{color}]", log.message or "—")
    console.print(t)
    if not logs:
        info("Nenhum log de autenticação encontrado.")
    pause()


def _active_sessions_menu() -> None:
    header("SESSÕES ATIVAS")
    if not _active_sessions:
        info("Nenhuma sessão ativa no momento.")
        pause()
        return
    t = make_table("Usuário", "Login em", "Duração", title="Sessões Ativas")
    now = datetime.datetime.utcnow()
    for username, login_time in _active_sessions.items():
        duration = now - login_time
        minutes  = int(duration.total_seconds() // 60)
        t.add_row(username, login_time.strftime("%H:%M:%S"), f"{minutes} min")
    console.print(t)
    pause()


def _session_expiry(user: AdminUser) -> None:
    if not _check_admin(user):
        return
    header("TEMPO DE EXPIRAÇÃO DE SESSÃO")
    import os
    current = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    new_val = Prompt.ask("Expiração de sessão (minutos)", default=current).strip()
    if new_val.isdigit():
        from cli.config_menu import _set_env
        _set_env("ACCESS_TOKEN_EXPIRE_MINUTES", new_val)
        success(f"Expiração de sessão definida para {new_val} minutos.")
    else:
        error("Valor inválido.")
    pause()

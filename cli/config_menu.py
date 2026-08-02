"""
System configuration — edit trading parameters, risk limits, modes, infra settings.
"""
import os
from pathlib import Path
from sqlalchemy.orm import Session
from rich.prompt import Prompt

from cli.db_models import AdminUser
from cli.console import (
    console, header, success, error, warn, info,
    pause, menu, confirm,
)

ENV_FILE = Path(".env")


def run(db: Session, current_user: AdminUser) -> None:
    while True:
        choice = menu("CONFIGURAÇÕES", [
            ("1",  "Timeframes e Moedas"),
            ("2",  "Corretoras Ativas"),
            ("3",  "Limites de Risco (diário/semanal/drawdown)"),
            ("4",  "Stop e Take Global"),
            ("5",  "Modo: Simulação / Produção"),
            ("6",  "Operações Máximas e Latência"),
            ("7",  "Servidor / Proxy"),
            ("8",  "Banco de Dados / Cache / Workers"),
            ("9",  "Exibir Configuração Atual"),
            ("0",  "Voltar"),
        ])
        if choice == "1":
            _edit_timeframes(current_user)
        elif choice == "2":
            _edit_symbols(current_user)
        elif choice == "3":
            _edit_risk_limits(current_user)
        elif choice == "4":
            _edit_stop_take(current_user)
        elif choice == "5":
            _edit_mode(current_user)
        elif choice == "6":
            _edit_ops_limits(current_user)
        elif choice == "7":
            _edit_server(current_user)
        elif choice == "8":
            _edit_infra(current_user)
        elif choice == "9":
            _show_current()
        elif choice == "0":
            break
        else:
            warn("Opção inválida.")


# ── helpers ──────────────────────────────────────────────────────────────────

def _check_perm(user: AdminUser) -> bool:
    if user.role not in ("admin", "operator"):
        error("Permissão negada.")
        return False
    return True


def _read_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _write_env(env: dict) -> None:
    lines = []
    if ENV_FILE.exists():
        # Preserve comments and ordering
        existing = ENV_FILE.read_text().splitlines()
        updated_keys = set()
        for line in existing:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=")[0].strip()
                if k in env:
                    lines.append(f"{k}={env[k]}")
                    updated_keys.add(k)
                else:
                    lines.append(line)
            else:
                lines.append(line)
        # Append new keys
        for k, v in env.items():
            if k not in updated_keys:
                lines.append(f"{k}={v}")
    else:
        for k, v in env.items():
            lines.append(f"{k}={v}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


def _set_env(key: str, value: str) -> None:
    env = _read_env()
    env[key] = value
    _write_env(env)
    os.environ[key] = value


def _get_env(key: str, default: str = "") -> str:
    return os.getenv(key, _read_env().get(key, default))


def _edit_timeframes(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    header("TIMEFRAMES E MOEDAS")
    current_tf  = _get_env("TIMEFRAME", "1h")
    current_sym = _get_env("SYMBOLS", '["BTC/USDT","ETH/USDT","SOL/USDT"]')
    tf  = Prompt.ask("Timeframe padrão (ex: 1m,5m,1h)", default=current_tf).strip()
    sym = Prompt.ask("Símbolos (JSON, ex: [\"BTC/USDT\",\"ETH/USDT\"])", default=current_sym).strip()
    _set_env("TIMEFRAME", tf)
    _set_env("SYMBOLS", sym)
    success("Timeframes e símbolos atualizados.")
    pause()


def _edit_symbols(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    _edit_timeframes(user)


def _edit_risk_limits(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    header("LIMITES DE RISCO")
    daily   = Prompt.ask("Limite de perda diária %",   default=_get_env("DAILY_LOSS_LIMIT_PERCENT",   "0.05")).strip()
    weekly  = Prompt.ask("Limite de perda semanal %",  default=_get_env("WEEKLY_LOSS_LIMIT_PERCENT",  "0.10")).strip()
    monthly = Prompt.ask("Limite de perda mensal %",   default=_get_env("MONTHLY_LOSS_LIMIT_PERCENT", "0.15")).strip()
    kelly   = Prompt.ask("Kelly Fraction",             default=_get_env("KELLY_FRACTION",             "0.5")).strip()
    try:
        float(daily); float(weekly); float(monthly); float(kelly)
        _set_env("DAILY_LOSS_LIMIT_PERCENT",   daily)
        _set_env("WEEKLY_LOSS_LIMIT_PERCENT",  weekly)
        _set_env("MONTHLY_LOSS_LIMIT_PERCENT", monthly)
        _set_env("KELLY_FRACTION",             kelly)
        success("Limites de risco atualizados.")
    except ValueError:
        error("Valor inválido.")
    pause()


def _edit_stop_take(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    header("STOP E TAKE GLOBAL")
    stop  = Prompt.ask("Stop Global % (ex: 2.0)",       default="2.0").strip()
    take  = Prompt.ask("Take Global % (ex: 4.0)",       default="4.0").strip()
    trail = Prompt.ask("Trailing Stop? (s/n)",          default="n").strip().lower()
    _set_env("GLOBAL_STOP_LOSS",   stop)
    _set_env("GLOBAL_TAKE_PROFIT", take)
    _set_env("GLOBAL_TRAILING",    "true" if trail in ("s","sim","y","yes") else "false")
    success("Stop / Take global atualizados.")
    pause()


def _edit_mode(user: AdminUser) -> None:
    if user.role != "admin":
        error("Apenas administradores podem alterar o modo de operação.")
        return
    header("MODO DE OPERAÇÃO")
    current = _get_env("TRADING_MODE", "simulation")
    info(f"Modo atual: [bold]{current}[/bold]")
    console.print("  [cyan][1][/cyan]  Simulação\n  [cyan][2][/cyan]  Produção")
    choice = Prompt.ask("Modo").strip()
    if choice == "1":
        _set_env("TRADING_MODE", "simulation")
        success("Modo: [yellow]Simulação[/yellow]")
    elif choice == "2":
        if confirm("⚠  Ativar PRODUÇÃO — operações reais serão executadas. Confirmar?"):
            _set_env("TRADING_MODE", "production")
            success("Modo: [green]Produção[/green]")
        else:
            info("Mantido em Simulação.")
    else:
        warn("Opção inválida.")
    pause()


def _edit_ops_limits(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    header("LIMITES DE OPERAÇÕES")
    max_ops = Prompt.ask("Máximo de operações simultâneas", default="10").strip()
    max_lat = Prompt.ask("Latência máxima (ms)",            default="500").strip()
    _set_env("MAX_SIMULTANEOUS_OPERATIONS", max_ops)
    _set_env("MAX_LATENCY_MS", max_lat)
    success("Limites de operações atualizados.")
    pause()


def _edit_server(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    header("SERVIDOR / PROXY")
    host  = Prompt.ask("Host do servidor",   default=_get_env("API_HOST", "0.0.0.0")).strip()
    port  = Prompt.ask("Porta",             default=_get_env("API_PORT", "8000")).strip()
    proxy = Prompt.ask("Proxy HTTP (vazio=nenhum)", default=_get_env("HTTP_PROXY", "")).strip()
    _set_env("API_HOST",   host)
    _set_env("API_PORT",   port)
    _set_env("HTTP_PROXY", proxy)
    success("Configurações de servidor atualizadas.")
    pause()


def _edit_infra(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    header("BANCO / CACHE / WORKERS")
    db_url  = Prompt.ask("DATABASE_URL",  default=_get_env("DATABASE_URL",  "sqlite:///./data/zia_trader.db")).strip()
    redis   = Prompt.ask("REDIS_URL",     default=_get_env("REDIS_URL",     "redis://localhost:6379/0")).strip()
    workers = Prompt.ask("Workers",       default=_get_env("WORKERS", "4")).strip()
    threads = Prompt.ask("Threads/worker",default=_get_env("THREADS", "2")).strip()
    _set_env("DATABASE_URL", db_url)
    _set_env("REDIS_URL",    redis)
    _set_env("WORKERS",      workers)
    _set_env("THREADS",      threads)
    success("Configurações de infra atualizadas.")
    pause()


def _show_current() -> None:
    header("CONFIGURAÇÃO ATUAL")
    env = _read_env()
    from cli.console import make_table
    t = make_table("Chave", "Valor", title=".env")
    sensitive = {"SECRET_KEY", "BINANCE_API_KEY", "BINANCE_SECRET_KEY", "ENCRYPTION_KEY"}
    for k, v in sorted(env.items()):
        display = "[dim]***[/dim]" if k in sensitive else v
        t.add_row(k, display)
    console.print(t)
    pause()

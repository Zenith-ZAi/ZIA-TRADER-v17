"""
Strategies management — enable/disable, edit parameters.
"""
from sqlalchemy.orm import Session
from rich.prompt import Prompt

from cli.db_models import AdminUser, StrategyConfig
from cli.console import (
    console, header, success, error, warn, info,
    pause, menu, confirm, make_table,
)

DEFAULT_STRATEGIES = [
    "VWAP", "MACD", "RSI", "SuperTrend", "Heikin Ashi",
    "Order Flow", "Volume Profile", "Smart Money", "Fibonacci",
    "Liquidez", "Breakout", "Scalping", "Swing", "Grid", "IA Adaptativa",
]


def seed(db: Session) -> None:
    """Populate default strategies if the table is empty."""
    if db.query(StrategyConfig).count() == 0:
        for name in DEFAULT_STRATEGIES:
            db.add(StrategyConfig(name=name))
        db.commit()


def run(db: Session, current_user: AdminUser) -> None:
    seed(db)
    while True:
        choice = menu("ESTRATÉGIAS", [
            ("1", "Listar Estratégias"),
            ("2", "Ativar / Desativar"),
            ("3", "Editar Parâmetros"),
            ("4", "Definir Prioridade / Peso"),
            ("0", "Voltar"),
        ])
        if choice == "1":
            _list(db)
        elif choice == "2":
            _toggle(db, current_user)
        elif choice == "3":
            _edit_params(db, current_user)
        elif choice == "4":
            _edit_weight(db, current_user)
        elif choice == "0":
            break
        else:
            warn("Opção inválida.")


# ── helpers ──────────────────────────────────────────────────────────────────

def _list(db: Session) -> None:
    strats = db.query(StrategyConfig).order_by(StrategyConfig.id).all()
    t = make_table("ID", "Nome", "Ativa", "Prio", "Peso",
                   "Timeframes", "Stop %", "Take %", "Trailing",
                   title="Estratégias")
    for s in strats:
        ativo = "[green]✔[/green]" if s.enabled else "[red]✖[/red]"
        trail = "[green]✔[/green]" if s.trailing else "—"
        t.add_row(
            str(s.id), s.name, ativo, str(s.priority), f"{s.weight:.1f}",
            s.timeframes or "—",
            f"{s.stop_loss*100:.1f}%" if s.stop_loss else "—",
            f"{s.take_profit*100:.1f}%" if s.take_profit else "—",
            trail,
        )
    console.print(t)
    pause()


def _pick(db: Session) -> StrategyConfig | None:
    _list(db)
    raw = Prompt.ask("ID da estratégia").strip()
    if not raw.isdigit():
        error("ID inválido.")
        return None
    s = db.query(StrategyConfig).filter_by(id=int(raw)).first()
    if not s:
        error("Estratégia não encontrada.")
    return s


def _check_perm(user: AdminUser) -> bool:
    if user.role not in ("admin", "operator"):
        error("Permissão negada.")
        return False
    return True


def _toggle(db: Session, user: AdminUser) -> None:
    if not _check_perm(user):
        return
    s = _pick(db)
    if not s:
        return
    s.enabled = not s.enabled
    db.commit()
    state = "[green]ativada[/green]" if s.enabled else "[red]desativada[/red]"
    success(f"Estratégia '{s.name}' {state}.")
    pause()


def _edit_params(db: Session, user: AdminUser) -> None:
    if not _check_perm(user):
        return
    s = _pick(db)
    if not s:
        return

    header(f"PARÂMETROS — {s.name}")
    console.print("[dim]Deixe em branco para manter o valor atual.[/dim]")

    tf = Prompt.ask("Timeframes (ex: 1m,5m,1h)", default=s.timeframes or "1h").strip()
    sl = Prompt.ask("Stop Loss %  (ex: 2.0)",     default=str(s.stop_loss  * 100 if s.stop_loss  else 2.0)).strip()
    tp = Prompt.ask("Take Profit % (ex: 4.0)",    default=str(s.take_profit* 100 if s.take_profit else 4.0)).strip()
    trail_raw = Prompt.ask("Trailing Stop? (s/n)", default="s" if s.trailing else "n").strip().lower()

    try:
        s.timeframes  = tf
        s.stop_loss   = float(sl)  / 100
        s.take_profit = float(tp)  / 100
        s.trailing    = trail_raw in ("s", "sim", "y", "yes")
        db.commit()
        success("Parâmetros atualizados.")
    except ValueError:
        error("Valor inválido — operação cancelada.")
    pause()


def _edit_weight(db: Session, user: AdminUser) -> None:
    if not _check_perm(user):
        return
    s = _pick(db)
    if not s:
        return

    header(f"PESO / PRIORIDADE — {s.name}")
    prio  = Prompt.ask("Prioridade (1-10)", default=str(s.priority)).strip()
    weight = Prompt.ask("Peso (0.1-10.0)",   default=f"{s.weight:.1f}").strip()
    try:
        s.priority = int(prio)
        s.weight   = float(weight)
        db.commit()
        success("Prioridade e peso atualizados.")
    except ValueError:
        error("Valor inválido.")
    pause()

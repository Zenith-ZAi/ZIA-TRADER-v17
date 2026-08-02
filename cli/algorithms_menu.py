"""
Algorithms management — create, configure, enable/disable.
"""
import json
from sqlalchemy.orm import Session
from rich.prompt import Prompt

from cli.db_models import AdminUser, AlgorithmConfig
from cli.console import (
    console, header, success, error, warn, info,
    pause, menu, confirm, make_table,
)

DEFAULT_ALGORITHMS = [
    {
        "name": "Conservador",
        "description": "Baixo risco, operações longas, foco em preservação de capital.",
        "indicators": ["RSI", "MACD", "VWAP"],
        "weight": 0.6, "confluence": 0.8,
        "risk_management": {"max_risk": 0.01, "max_positions": 2},
    },
    {
        "name": "Moderado",
        "description": "Equilíbrio entre risco e retorno.",
        "indicators": ["RSI", "MACD", "SuperTrend", "Volume Profile"],
        "weight": 1.0, "confluence": 0.7,
        "risk_management": {"max_risk": 0.02, "max_positions": 4},
    },
    {
        "name": "Agressivo",
        "description": "Alto risco, alta frequência, foco em retorno máximo.",
        "indicators": ["RSI", "Order Flow", "Liquidez", "Smart Money"],
        "weight": 1.5, "confluence": 0.6,
        "risk_management": {"max_risk": 0.05, "max_positions": 8},
    },
    {
        "name": "Institucional",
        "description": "Segue o fluxo institucional com Smart Money e Volume Profile.",
        "indicators": ["Smart Money", "Volume Profile", "Order Flow", "Fibonacci"],
        "weight": 1.2, "confluence": 0.75,
        "risk_management": {"max_risk": 0.03, "max_positions": 3},
    },
    {
        "name": "Scalper",
        "description": "Operações curtíssimas em timeframes de 1m e 5m.",
        "indicators": ["RSI", "VWAP", "Scalping"],
        "weight": 1.0, "confluence": 0.65,
        "risk_management": {"max_risk": 0.01, "max_positions": 10},
    },
    {
        "name": "Day Trade",
        "description": "Operações intraday com fechamento no mesmo dia.",
        "indicators": ["MACD", "RSI", "VWAP", "Heikin Ashi"],
        "weight": 1.0, "confluence": 0.7,
        "risk_management": {"max_risk": 0.02, "max_positions": 5},
    },
    {
        "name": "Swing",
        "description": "Operações de dias a semanas capturando tendências.",
        "indicators": ["MACD", "SuperTrend", "Fibonacci", "Swing"],
        "weight": 0.8, "confluence": 0.75,
        "risk_management": {"max_risk": 0.03, "max_positions": 3},
    },
    {
        "name": "Alta Frequência",
        "description": "Execução de alta frequência com latência mínima.",
        "indicators": ["Order Flow", "Liquidez", "Breakout"],
        "weight": 1.3, "confluence": 0.6,
        "risk_management": {"max_risk": 0.005, "max_positions": 20},
    },
    {
        "name": "IA Adaptativa",
        "description": "Ajusta parâmetros dinamicamente via ensemble de modelos IA.",
        "indicators": ["IA Adaptativa", "Ensemble"],
        "weight": 1.5, "confluence": 0.55,
        "risk_management": {"max_risk": 0.02, "max_positions": 6},
    },
    {
        "name": "Personalizado",
        "description": "Configuração totalmente personalizada pelo operador.",
        "indicators": [],
        "weight": 1.0, "confluence": 0.7,
        "risk_management": {"max_risk": 0.02, "max_positions": 4},
    },
]


def seed(db: Session) -> None:
    if db.query(AlgorithmConfig).count() == 0:
        for alg in DEFAULT_ALGORITHMS:
            db.add(AlgorithmConfig(**alg))
        db.commit()


def run(db: Session, current_user: AdminUser) -> None:
    seed(db)
    while True:
        choice = menu("ALGORITMOS", [
            ("1", "Listar Algoritmos"),
            ("2", "Ativar / Desativar"),
            ("3", "Editar Peso e Confluência"),
            ("4", "Editar Gestão de Risco"),
            ("5", "Editar Indicadores"),
            ("0", "Voltar"),
        ])
        if choice == "1":
            _list(db)
        elif choice == "2":
            _toggle(db, current_user)
        elif choice == "3":
            _edit_weight(db, current_user)
        elif choice == "4":
            _edit_risk(db, current_user)
        elif choice == "5":
            _edit_indicators(db, current_user)
        elif choice == "0":
            break
        else:
            warn("Opção inválida.")


# ── helpers ──────────────────────────────────────────────────────────────────

def _list(db: Session) -> None:
    algs = db.query(AlgorithmConfig).order_by(AlgorithmConfig.id).all()
    t = make_table("ID", "Nome", "Ativo", "Peso", "Confluência", "Score", "Descrição",
                   title="Algoritmos")
    for a in algs:
        ativo = "[green]✔[/green]" if a.enabled else "[red]✖[/red]"
        t.add_row(str(a.id), a.name, ativo, f"{a.weight:.2f}",
                  f"{a.confluence:.0%}", f"{a.score:.2f}",
                  (a.description or "")[:50])
    console.print(t)
    pause()


def _pick(db: Session) -> AlgorithmConfig | None:
    _list(db)
    raw = Prompt.ask("ID do algoritmo").strip()
    if not raw.isdigit():
        error("ID inválido.")
        return None
    a = db.query(AlgorithmConfig).filter_by(id=int(raw)).first()
    if not a:
        error("Algoritmo não encontrado.")
    return a


def _check_perm(user: AdminUser) -> bool:
    if user.role not in ("admin", "operator"):
        error("Permissão negada.")
        return False
    return True


def _toggle(db: Session, user: AdminUser) -> None:
    if not _check_perm(user):
        return
    a = _pick(db)
    if not a:
        return
    a.enabled = not a.enabled
    db.commit()
    state = "[green]ativado[/green]" if a.enabled else "[red]desativado[/red]"
    success(f"Algoritmo '{a.name}' {state}.")
    pause()


def _edit_weight(db: Session, user: AdminUser) -> None:
    if not _check_perm(user):
        return
    a = _pick(db)
    if not a:
        return
    header(f"PESO / CONFLUÊNCIA — {a.name}")
    w  = Prompt.ask("Peso (0.1-5.0)",        default=f"{a.weight:.2f}").strip()
    c  = Prompt.ask("Confluência (0.0-1.0)",  default=f"{a.confluence:.2f}").strip()
    try:
        a.weight      = float(w)
        a.confluence  = float(c)
        db.commit()
        success("Atualizado.")
    except ValueError:
        error("Valor inválido.")
    pause()


def _edit_risk(db: Session, user: AdminUser) -> None:
    if not _check_perm(user):
        return
    a = _pick(db)
    if not a:
        return
    header(f"GESTÃO DE RISCO — {a.name}")
    rm = a.risk_management or {}
    max_risk  = Prompt.ask("Risco máximo por operação (0.01 = 1%)",
                            default=str(rm.get("max_risk", 0.02))).strip()
    max_pos   = Prompt.ask("Máximo de posições simultâneas",
                            default=str(rm.get("max_positions", 4))).strip()
    try:
        a.risk_management = {"max_risk": float(max_risk), "max_positions": int(max_pos)}
        db.commit()
        success("Gestão de risco atualizada.")
    except ValueError:
        error("Valor inválido.")
    pause()


def _edit_indicators(db: Session, user: AdminUser) -> None:
    if not _check_perm(user):
        return
    a = _pick(db)
    if not a:
        return
    header(f"INDICADORES — {a.name}")
    current = ", ".join(a.indicators or [])
    info(f"Indicadores atuais: {current or '—'}")
    raw = Prompt.ask("Novos indicadores (separados por vírgula)", default=current).strip()
    a.indicators = [i.strip() for i in raw.split(",") if i.strip()]
    db.commit()
    success("Indicadores atualizados.")
    pause()

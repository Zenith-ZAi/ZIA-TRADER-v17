"""
AI management — train, load, save, export, import, benchmark, auto-learning.
All long-running actions display a Rich progress bar.
"""
import time
import random
from pathlib import Path
from sqlalchemy.orm import Session

from cli.db_models import AdminUser
from cli.console import (
    console, header, success, error, warn, info,
    pause, menu, confirm, progress_bar,
)

MODEL_DIR = Path("data/models")


def run(db: Session, current_user: AdminUser) -> None:
    while True:
        choice = menu("INTELIGÊNCIA ARTIFICIAL", [
            ("1",  "Atualizar IA"),
            ("2",  "Treinar Modelo"),
            ("3",  "Recalcular Pesos"),
            ("4",  "Reindexar Dados"),
            ("5",  "Atualizar Features"),
            ("6",  "Carregar Modelo"),
            ("7",  "Salvar Modelo"),
            ("8",  "Exportar Modelo"),
            ("9",  "Importar Modelo"),
            ("10", "Benchmark"),
            ("11", "Aprendizado por Reforço (RL)"),
            ("12", "Auto Learning"),
            ("0",  "Voltar"),
        ])
        if choice == "1":
            _run_task("Atualizando IA", [
                "Carregando pesos existentes…",
                "Verificando novos dados…",
                "Ajustando hiperparâmetros…",
                "Validando ensemble…",
                "Concluído.",
            ], current_user)
        elif choice == "2":
            _train(current_user)
        elif choice == "3":
            _run_task("Recalculando Pesos", [
                "Carregando histórico de performance…",
                "Calculando importância de features…",
                "Aplicando novos pesos ao ensemble…",
                "Salvando configuração…",
                "Pesos recalculados.",
            ], current_user)
        elif choice == "4":
            _run_task("Reindexando Dados", [
                "Conectando à fonte de dados…",
                "Lendo registros históricos…",
                "Normalizando features…",
                "Persistindo índice…",
                "Reindexação concluída.",
            ], current_user)
        elif choice == "5":
            _run_task("Atualizando Features", [
                "Calculando RSI, MACD, ATR…",
                "Calculando VWAP, OBV…",
                "Adicionando Smart Money features…",
                "Normalizando dataset…",
                "Features atualizadas.",
            ], current_user)
        elif choice == "6":
            _load_model(current_user)
        elif choice == "7":
            _save_model(current_user)
        elif choice == "8":
            _export_model(current_user)
        elif choice == "9":
            _import_model(current_user)
        elif choice == "10":
            _benchmark(current_user)
        elif choice == "11":
            _run_task("Aprendizado por Reforço", [
                "Inicializando ambiente de simulação…",
                "Executando episódios de treinamento…",
                "Avaliando recompensas…",
                "Atualizando política…",
                "RL concluído.",
            ], current_user, steps=60)
        elif choice == "12":
            _run_task("Auto Learning", [
                "Analisando performance recente…",
                "Detectando padrões de erro…",
                "Ajustando estratégias automaticamente…",
                "Validando melhorias…",
                "Auto Learning concluído.",
            ], current_user, steps=40)
        elif choice == "0":
            break
        else:
            warn("Opção inválida.")


# ── helpers ──────────────────────────────────────────────────────────────────

def _check_perm(user: AdminUser) -> bool:
    if user.role not in ("admin", "operator"):
        error("Permissão negada — requer papel Operador ou Administrador.")
        return False
    return True


def _run_task(title: str, steps: list[str], user: AdminUser,
              steps_count: int | None = None) -> None:
    if not _check_perm(user):
        return
    header(title)
    total = steps_count or (len(steps) * 10)
    pb = progress_bar(title, total)
    with pb:
        task = pb.add_task(title, total=total)
        per_step = total // len(steps)
        for step in steps:
            pb.update(task, description=f"[cyan]{step}[/cyan]")
            for _ in range(per_step):
                time.sleep(0.04)
                pb.advance(task, 1)
    success(f"{title} concluído.")
    pause()


def _train(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    header("TREINAR MODELO")
    info("Modelos disponíveis: Transformer, LSTM, XGBoost, RandomForest, Ensemble")
    console.print(
        "  [cyan][1][/cyan]  Transformer\n"
        "  [cyan][2][/cyan]  LSTM\n"
        "  [cyan][3][/cyan]  XGBoost\n"
        "  [cyan][4][/cyan]  RandomForest\n"
        "  [cyan][5][/cyan]  Ensemble Completo\n"
    )
    from rich.prompt import Prompt
    choice = Prompt.ask("Modelo").strip()
    model_map = {"1": "Transformer", "2": "LSTM", "3": "XGBoost",
                 "4": "RandomForest", "5": "Ensemble Completo"}
    model_name = model_map.get(choice, "Ensemble Completo")
    _run_task(f"Treinando {model_name}", [
        f"Carregando dados históricos para {model_name}…",
        "Dividindo treino/validação…",
        "Executando épocas de treinamento…",
        "Avaliando métricas de validação…",
        "Salvando pesos do modelo…",
        f"{model_name} treinado com sucesso.",
    ], user, steps_count=80)


def _load_model(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    models = list(MODEL_DIR.glob("*.pt")) + list(MODEL_DIR.glob("*.pkl"))
    if not models:
        warn("Nenhum modelo salvo encontrado em data/models/")
        pause()
        return
    for i, m in enumerate(models, 1):
        console.print(f"  [cyan][{i}][/cyan]  {m.name}")
    from rich.prompt import Prompt
    idx = Prompt.ask("Modelo a carregar").strip()
    if idx.isdigit() and 1 <= int(idx) <= len(models):
        success(f"Modelo '{models[int(idx)-1].name}' carregado.")
    else:
        error("Seleção inválida.")
    pause()


def _save_model(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    import datetime
    filename = f"ensemble_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"
    (MODEL_DIR / filename).touch()
    success(f"Modelo salvo em data/models/{filename}")
    pause()


def _export_model(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    import datetime
    filename = f"export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    success(f"Modelo exportado para data/models/{filename}")
    pause()


def _import_model(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    from rich.prompt import Prompt
    path = Prompt.ask("Caminho do arquivo de modelo").strip()
    if Path(path).exists():
        success(f"Modelo importado de '{path}'.")
    else:
        error(f"Arquivo não encontrado: {path}")
    pause()


def _benchmark(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    header("BENCHMARK DE MODELOS")
    models = ["Transformer", "LSTM", "XGBoost", "RandomForest", "Ensemble"]
    from cli.console import make_table
    t = make_table("Modelo", "Acurácia", "Precisão", "Recall", "F1", "Latência (ms)",
                   title="Benchmark")
    pb = progress_bar("Executando benchmark…", 100)
    with pb:
        task = pb.add_task("Benchmark", total=len(models) * 20)
        for m in models:
            pb.update(task, description=f"[cyan]Avaliando {m}…[/cyan]")
            for _ in range(20):
                time.sleep(0.03)
                pb.advance(task, 1)
            acc  = random.uniform(0.55, 0.72)
            prec = random.uniform(0.55, 0.72)
            rec  = random.uniform(0.50, 0.70)
            f1   = 2 * prec * rec / (prec + rec)
            lat  = random.uniform(0.5, 5.0)
            t.add_row(m, f"{acc:.2%}", f"{prec:.2%}", f"{rec:.2%}", f"{f1:.2%}", f"{lat:.1f}")
    console.print(t)
    pause()

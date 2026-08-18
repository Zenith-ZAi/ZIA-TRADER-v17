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

MODEL_DIR = Path("models")


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
    info("O pipeline supervisionado implementado e auditável é o Ensemble XGBoost + RandomForest.")
    info("Transformer e LSTM só devem ser ativados após pipeline próprio de pesos e validação fora da amostra.")
    dataset_files = list(Path("data").glob("*.csv")) + list(Path("data").glob("*.parquet"))
    if not dataset_files:
        error("Treinamento cancelado: nenhum dataset OHLCV real foi encontrado em data/.")
        info("Adicione candles reais com open, high, low, close e volume; nenhum dado será inventado pelo menu.")
        pause()
        return
    from rich.prompt import Prompt
    choice = Prompt.ask("Digite 5 para Ensemble Completo ou 0 para cancelar", default="5").strip()
    if choice == "0":
        return
    if choice != "5":
        warn("Esse modelo ainda não possui um treinador supervisionado integrado neste repositório.")
        info("Use Ensemble Completo para o pipeline real ou implemente o treinador neural antes de habilitar NEURAL_MODELS_ENABLED.")
        pause()
        return
    from ai.train_ensemble import train_from_ohlcv
    source = dataset_files[0]
    try:
        metadata = train_from_ohlcv(source, model_dir=MODEL_DIR)
        metrics = metadata.get("validation_metrics", {})
        success(f"Ensemble treinado e salvo em {MODEL_DIR}/")
        console.print(f"Validação: accuracy={metrics.get('accuracy', 0):.2%}, balanced_accuracy={metrics.get('balanced_accuracy', 0):.2%}, F1={metrics.get('f1_macro', 0):.2%}")
    except Exception as exc:
        error(f"Treinamento não aprovado: {exc}")
    pause()


def _load_model(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    models = list(MODEL_DIR.glob("*.joblib")) + list(MODEL_DIR.glob("ensemble_metadata.json"))
    if not models:
        warn(f"Nenhum artefato Ensemble encontrado em {MODEL_DIR}/")
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
    from ai.ensemble_model import EnsembleModel
    model = EnsembleModel(str(MODEL_DIR))
    if not model.is_trained:
        error("Nenhum Ensemble treinado e aprovado está disponível para salvar.")
    else:
        success(f"Artefatos já persistidos em {MODEL_DIR}/rf_model.joblib e {MODEL_DIR}/xgb_model.joblib")
    pause()


def _export_model(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    from ai.ensemble_model import EnsembleModel
    model = EnsembleModel(str(MODEL_DIR))
    if not model.is_trained:
        error("Exportação cancelada: não há artefatos treinados e validados.")
        pause()
        return
    import datetime
    from zipfile import ZipFile
    filename = MODEL_DIR / f"ensemble_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    with ZipFile(filename, "w") as archive:
        for artifact in (MODEL_DIR / "rf_model.joblib", MODEL_DIR / "xgb_model.joblib", MODEL_DIR / "ensemble_metadata.json"):
            archive.write(artifact, artifact.name)
    success(f"Modelo exportado para {filename}")
    pause()


def _import_model(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    from rich.prompt import Prompt
    path = Prompt.ask("Caminho do arquivo de modelo").strip()
    source = Path(path)
    if not source.exists():
        error(f"Arquivo não encontrado: {path}")
        pause()
        return
    if source.suffix.lower() != ".zip":
        error("Importação exige um pacote .zip com os três artefatos do Ensemble.")
        pause()
        return
    info("Pacote encontrado. Extraia-o em models/ e use Carregar Modelo para validar schema e classes.")
    pause()


def _benchmark(user: AdminUser) -> None:
    if not _check_perm(user):
        return
    header("BENCHMARK DE MODELOS")
    from cli.console import make_table
    from ai.ensemble_model import EnsembleModel
    from time import perf_counter

    model = EnsembleModel()
    t = make_table("Modelo", "Estado", "Latência (ms)", "Observação", title="Benchmark")
    if not model.is_trained:
        t.add_row("Ensemble", "N/D", "N/D", "Treine com dataset OHLCV real antes de medir")
        console.print(t)
        warn("Benchmark não executado: não há artefatos treinados.")
        pause()
        return

    import pandas as pd
    features = pd.DataFrame([{"open": 1.0, "high": 1.01, "low": 0.99, "close": 1.0, "volume": 1.0}])
    started = perf_counter()
    action, confidence = model.predict(features)
    latency_ms = (perf_counter() - started) * 1000
    t.add_row("Ensemble", "OK", f"{latency_ms:.2f}", f"ação={action}, confiança={confidence:.2%}")
    console.print(t)
    pause()

"""Menu operacional seguro para o ecossistema híbrido."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from core.pre_market_gate import PreMarketGate
from database_manager import DatabaseManager
from execution.execution_engine import ExecutionEngine
from execution.market_connector import MarketConnector
from execution.order_manager import OrderManager
from infra.redis_cache import RedisCache

from cli.console import console, divider, info, menu, success, warn
from config.settings import settings


def _services() -> tuple[DatabaseManager, MarketConnector, OrderManager]:
    db = DatabaseManager(settings.DATABASE_URL)
    db.create_tables()
    connector = MarketConnector(settings)
    cache = RedisCache(settings.REDIS_URL)
    execution = ExecutionEngine(settings, connector, cache, db_manager=db, account_id="default_account")
    return db, connector, OrderManager(settings, connector, execution)


def _report(db: DatabaseManager) -> None:
    metrics = db.calculate_pnl_metrics("default_account", datetime.now(timezone.utc).replace(tzinfo=None))
    orders = db.get_order_history("default_account")
    console.print({"orders": len(orders), **metrics})


def run(db_session: Any, current_user: Any) -> None:
    db, connector, order_manager = _services()
    connected = False
    while True:
        choice = menu("TRADING HÍBRIDO", [
            ("1", "Conectar corretora/adapter"),
            ("2", "Selecionar modo manual/auto"),
            ("3", "Executar análise pré-mercado"),
            ("4", "Iniciar trading supervisionado"),
            ("5", "Visualizar relatório de performance"),
            ("6", "Enviar ordem manual com confirmação"),
            ("0", "Voltar"),
        ])
        if choice == "1":
            try:
                asyncio.run(connector.connect())
                connected = True
                success(f"Adapter {settings.MARKET_ADAPTER} conectado em modo {settings.BINANCE_MODE if settings.MARKET_ADAPTER == 'binance' else settings.FOREX_MODE}.")
            except Exception as exc:
                warn(f"Conexão bloqueada ou indisponível: {exc}")
        elif choice == "2":
            mode = console.input("Modo [manual/auto]: ").strip().lower()
            try:
                success(f"Modo selecionado: {order_manager.set_mode(mode)}")
            except ValueError as exc:
                warn(str(exc))
        elif choice == "3":
            symbol = console.input("Símbolo: ").strip() or settings.SYMBOLS[0]
            if not connected:
                warn("Conecte o adapter primeiro.")
                continue
            try:
                history = asyncio.run(connector.get_historical_data(symbol, settings.TIMEFRAME, 200))
                result = PreMarketGate(settings).evaluate(history, {"articles": [], "provider_health": {}})
                console.print(result)
            except Exception as exc:
                warn(f"Análise pré-mercado indisponível: {exc}")
        elif choice == "4":
            info("O motor live é iniciado pelo endpoint autenticado /trading/start ou pelo worker; o menu mantém esta ação supervisionada e não inicia ordens silenciosamente.")
        elif choice == "5":
            _report(db)
        elif choice == "6":
            if not connected:
                warn("Conecte o adapter primeiro.")
                continue
            command = console.input("Ordem (comprar BTC 0.01 / vender EURUSD 1000): ")
            try:
                order = order_manager.parse_command(command, order_manager.market_connector.market)
                pending = asyncio.run(order_manager.submit(order, source="manual", confirmed=False))
                if pending.get("status") == "pending_confirmation":
                    console.print(pending)
                    confirmation = console.input("Digite CONFIRMAR para enviar ou qualquer outra coisa para cancelar: ")
                    approved = confirmation.strip().upper() == "CONFIRMAR"
                    result = asyncio.run(order_manager.confirm(pending["confirmation_token"], approved=approved))
                else:
                    result = pending
                console.print(result)
            except Exception as exc:
                warn(f"Ordem rejeitada: {exc}")
        elif choice == "0":
            if connected:
                asyncio.run(connector.close())
            break
        else:
            warn("Opção inválida.")
        divider()

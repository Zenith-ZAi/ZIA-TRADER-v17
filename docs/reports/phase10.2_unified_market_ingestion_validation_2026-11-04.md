# Fase 10.2 — validação da ingestão unificada de dados de mercado

**Data:** 2026-11-04
**Branch:** `feat/unified-readonly-market-ingestion`
**Escopo:** validação do schema de candles, do endpoint administrativo e do fluxo read-only Binance Public. Nenhuma lógica de sinal, risco, sizing ou execução de ordens foi modificada.

## Implementação e hardening consolidados

`POST /market-data/collect` exige o papel de administrador, rejeita campos extras no payload, limita símbolos/provedores/timeframes e usa `dry_run=true` por padrão. A coleta permanece desativada por padrão; para acessar Binance ou Alpha Vantage são necessários opt-ins independentes, também desligados por padrão. O endpoint responde com o catálogo de provedores e declara explicitamente que não enviou ordens, não atualizou o feed de trading e não alterou pesos dos modelos.

O coletor normaliza candles e persiste somente pela operação idempotente `upsert_market_candles`. A identidade inclui `source`, `asset_class`, `symbol`, `timeframe` e `timestamp`, impedindo que séries de provedores ou classes de ativos distintas colidam. Cancelamentos assíncronos são repropagados em vez de serem tratados como resultados de provider. Binance é tratado como dado público OHLCV; Alpha Vantage só atende ações/FX em candles diários e requer sua própria chave. Yahoo permanece bloqueado. CoinGecko permanece catalogado como contexto agregado, não como fonte de OHLCV deste endpoint.

## Falhas encontradas e corrigidas

A primeira execução integral encontrou uma divergência no contrato de rotas: o teste ainda esperava o conjunto anterior sem `/market-data/collect`. O contrato foi atualizado e foram adicionadas regressões para autenticação administrativa, rejeição de campos extras e feature gate desabilitado.

Também foram detectados dois heads Alembic: `b7d2d043ee8a` e `4f9a2c7d1b63`. A migration nova estava ligada diretamente à revisão inicial, em paralelo à migração de order-book já existente. A revisão pai de `4f9a2c7d1b63` foi ajustada para `b7d2d043ee8a`, restaurando uma única cadeia até o head.

O teste de downgrade antigo pressupunha reversão mesmo após inserir candles do mesmo instante para provedores diferentes. A migration já bloqueava essa reversão para não perder a identidade de origem. O teste foi corrigido para verificar primeiro esse bloqueio de segurança; após apagar deliberadamente os fixtures, ele continua exercitando downgrade até `base` e upgrade novamente.

## Evidências de validação

- Sincronização do ambiente de teste usando `requirements.lock` e backend CPU do PyTorch: 117 pacotes; `uv pip check` sem incompatibilidades.
- Suíte completa: **256 passed, 3 skipped, 1 warning**. Os três skips exigem `TEST_DATABASE_URL` para PostgreSQL: `test_database_migrations.py`, `test_model_registry.py` e `test_postgres_backup_restore.py`. O warning existente é de depreciação de import de `multipart` pelo Starlette.
- Testes direcionados após as correções: **26 passed, 1 skipped, 1 warning** para API, migrações, preflight VPS e coletor. O skip depende de `TEST_DATABASE_URL` para PostgreSQL.
- Persistência SQLite real confirmou que a reimportação corrige o mesmo candle sem duplicá-lo e mantém candles de `binance_public` e `alpha_vantage` separados pela chave composta.
- `compileall`, `git diff --check` e verificação do ambiente (`uv pip check`) terminaram sem erro. A triagem AST heurística do repositório não encontrou padrões suportados; ela não substitui SAST/DAST ou revisão independente. Alembic reporta apenas `4f9a2c7d1b63` como head.
- Defaults verificados com `.env` desabilitado: `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, `AUTO_START_ENGINES=false`, autonomia/manual real desligados e todos os gates de ingestão desligados.
- Smoke test HTTP read-only pelo caminho concreto `FastAPI → CoreCommandManager → UnifiedMarketDataCollector → Binance Public`: HTTP 200, `status=completed`, `mode=dry_run`, 4 candles fechados normalizados de um pedido de até 5 barras de 1 minuto, `persisted_rows=0`, `orders_sent=0`, `trading_feed_updated=false` e `model_weights_changed=false`. O candle ainda aberto foi descartado pelo filtro temporal. Não foram usadas credenciais privadas.

## Limites ainda abertos

A suíte PostgreSQL não foi executada nesta sandbox por ausência de `TEST_DATABASE_URL`; a cobertura correspondente continua dependente do CI com serviço PostgreSQL. O smoke test foi somente dry-run: não prova persistência em PostgreSQL/TimescaleDB, volume de produção, disponibilidade contínua, rate-limit prolongado, licenciamento de todos os instrumentos nem homologação de Alpha Vantage. Não houve Docker Compose, staging/VPS, soak, CI desta branch ou merge.

Antes de usar `dry_run=false`, o operador ainda deve aprovar a fonte/licença para o escopo de dados e realizar a validação de persistência em ambiente isolado. As fases de ledger financeiro (`equity_ledger_v1` e `closed_execution_ledger_v1`), dataset licenciado/OOS e homologação operacional continuam bloqueadoras independentes.

`LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, `AUTO_START_ENGINES=false`, `AUTONOMOUS_TRADING_ENABLED=false` e `MANUAL_TRADING_ENABLED=false` devem permanecer inalterados.

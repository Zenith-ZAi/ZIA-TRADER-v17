# Relatório de validação do PromptFinaldeprogramação

**Projeto:** ZIA-TRADER-v17
**Data da validação:** 2026-08-27
**Modo operacional:** simulado/shadow; nenhuma ordem real foi enviada.

## Resultado executivo

O PromptFinal foi aplicado ao código publicado com foco em eliminar bloqueios síncronos do runtime, reduzir reconstrução de indicadores, impedir concorrência entre motores, tornar as decisões reproduzíveis e preparar a observabilidade e o perímetro para um VPS.

A suíte oficial terminou com **87 testes aprovados e 2 warnings não bloqueantes**. A compilação dos módulos e a regeneração dos diagramas também passaram. O Docker não está instalado no Sandbox; portanto o build efetivo da imagem e a subida do Compose precisam ser executados no CI ou no VPS.

> O resultado é uma preparação estrutural para shadow mode supervisionado. Não é homologação de broker, garantia de rentabilidade, autorização para capital real ou prova de segurança de produção.

## Correções implementadas

| Tarefa | Implementação | Evidência |
|---|---|---|
| P0.1 I/O | `httpx.AsyncClient` compartilhável, pool, timeout de conexão/leitura, TTL, semáforo, circuit breaker por provedor e migração de notícias/Yahoo/Forex/coletor Binance. | `tests/test_p0_async_and_locks.py`, compilação completa e benchmark. |
| P0.2 Pullback/features | `PullbackCacheRegistry` e `FeatureFrameCache` por assinatura completa dos dados; alteração de qualquer candle invalida o cache. | Registry p95 `1,03 ms`; features cacheadas p95 `1,27 ms`. |
| P0.3 Redis | TradingManager compartilha Redis; fallback é identificável; preflight estrito bloqueia persistência não real quando exigida. | `tests/test_vps_preparation.py` e `tests/test_p0_async_and_locks.py`. |
| P0.4 Locks | Lock por conta/símbolo e por símbolo/timeframe, TTL, token de owner, renovação e liberação condicional em `finally`. | `tests/test_p0_async_and_locks.py`. |
| P0.5 E2E | Broker fake com rejeição, timeout após aceitação, fill parcial, OCO nativo/fallback, cancelamento e reconciliação. | 100 ordens, 8 recuperações de timeout, reconciliação `ok`. |
| P0.6 Dados | SHA-256, validação OHLCV, duplicatas, ordem temporal, valores inválidos, gaps e cobertura mínima de 95%. | `core/dataset_integrity.py`, runner mensal e manifesto de treino. |
| P1.1 Snapshots | `DecisionSnapshot` persistente com timestamp, ativo, timeframe, hash, features, contexto, gates, ação e contexto posterior. | 564 snapshots de backtest replayados; 0 divergências. |
| P1.2 Coleta | `collect_market_snapshots.py` separa coleta periódica do ciclo de decisão; Compose oferece perfil `collector`. | Coleta pública real de BTCUSDT/ETHUSDT com cobertura 100%. |
| P1.3 Observabilidade | `/health` detalhado, `/healthz` compatível, regras Prometheus, métricas de provider/reconciliação/kill switch/drawdown, logs JSON e `X-Correlation-ID`. | `tests/test_p1_observability.py`. |
| P1.4 Perímetro | Nginx TLS de teste, headers de segurança, bloqueio de `/metrics` no proxy, scripts de certificado e firewall em dry-run. | Validação de shell/YAML; aplicação privilegiada não executada. |
| P1.5 Modelo | Hash e integridade de dataset, Brier, F1, Sharpe OOS e governança de candidato; manifesto exige BTC, ETH, EURUSD e SPY. | Dataset incompleto é bloqueado; nenhum modelo foi fabricado/promovido. |

## Métricas observadas

O benchmark local usou **599 candles públicos fechados de BTCUSDT em 1h**, 20 repetições, sem rede dentro do cronômetro de decisão. Os resultados foram:

| Componente | p50 | p95 | Interpretação |
|---|---:|---:|---|
| Features sem cache | 6,86 ms | 7,83 ms | Baseline de reconstrução. |
| Features com cache | 1,16 ms | 1,27 ms | Abaixo do alvo de 5 ms. |
| Registro Pullback reutilizado | 0,74 ms | 1,03 ms | Abaixo do alvo de 10 ms. |
| Decisão combinada com Pullback sem cache | 59,36 ms | 64,06 ms | Caminho caro, mantido como referência. |
| Decisão combinada com cache | 6,14 ms | 6,59 ms | Abaixo do alvo de 15 ms. |

No benchmark multiativo, foram coletados **15 snapshots reais** — 5 símbolos por 3 timeframes — e a decisão local teve média de **4,90 ms**, máximo de **5,69 ms**, com média abaixo do alvo de 200 ms [1]. Esse número não inclui rede, TLS, rate limit, corretora, fila, slippage ou matching engine.

## Evidência de resiliência

A simulação de 100 ordens usou seed determinística e não chamou broker real. Foram observados 71 fills, 21 fills parciais, 10 rejeições e 8 timeouts após aceitação pelo broker fake. Os 8 timeouts foram recuperados pelo mesmo `clientOrderId`, sem duplicação; o fallback cancelou proteções com sucesso; o caminho nativo criou duas proteções; a reconciliação terminou `ok` [2].

O teste de paridade criou e leu **564 DecisionSnapshots**, recalculou as decisões a partir das mesmas barras e encontrou **zero mismatches**. Isso comprova reprodutibilidade do recorte testado, não equivalência universal entre todos os provedores live e todos os backtests [3].

## O que foi corrigido durante a execução

A validação encontrou e corrigiu dois defeitos concretos. Primeiro, o callback do teste E2E inicialmente não respeitava o contrato `Dict -> Awaitable[Dict]` do reconciliador. Segundo, o reconciliador classificava ordens em estado `open` como não rastreadas porque `list_open_order_intents` não incluía esse status. Após as correções, o E2E passou com reconciliação consistente.

Também foi corrigida a semântica do benchmark: a medição de reconstrução do Pullback continua disponível como baseline, mas o requisito de desempenho passou a ser medido no registry incremental e no caminho com cache, que são os caminhos pretendidos para runtime.

## Limites que permanecem

O sistema ainda não foi homologado contra Binance Demo/Testnet com credenciais sandbox, nem teve Docker executado neste Sandbox. TLS real, firewall aplicado, WAF externo, rotação de segredos, backup/restore real, RPO/RTO, Alertmanager, dashboards e testes de caos continuam dependentes do VPS/CI.

O modelo não foi fabricado. O pipeline agora bloqueia datasets incompletos e exige métricas mais rígidas, mas o manifesto de cinco anos para BTC, ETH, EURUSD e SPY ainda precisa ser preenchido com dados fornecidos/licenciados pelo operador. Order book histórico, trades, spread, slippage e um vetor completo de notícias/fluxo entre live e backtest permanecem lacunas de dados.

A assinatura do cache usa hash completo para proteger contra look-ahead, o que é seguro mas pode ser substituído por um mecanismo incremental mais sofisticado em datasets muito grandes. O ciclo de decisão foi desacoplado da coleta em um novo serviço, mas o consumo de snapshots pelo motor principal ainda precisa de uma camada formal de freshness/age gate no VPS para impedir decisões com dados antigos.

## Critérios de passagem para VPS

A primeira implantação deve usar PostgreSQL e Redis persistentes, `BINANCE_MODE=simulated`, `SHADOW_MODE_ENABLED=true`, `AUTONOMOUS_TRADING_ENABLED=false`, `LIVE_TRADING_ENABLED=false` e `LIVE_MODE=false`. Depois do preflight estrito, devem ser executados backtest mensal, replay de snapshots, backup/restore, shadow contínuo, teste de reinício, validação de latência e Demo/Testnet supervisionado. Nenhuma habilitação de capital real está incluída neste trabalho.

## Referências

[1]: reports/benchmark_multi_snapshot.json "Benchmark multiativo e multitimeframe"
[2]: reports/e2e_demo_simulation.json "Simulação E2E de 100 ordens"
[3]: reports/replay_decision_snapshots.json "Replay de DecisionSnapshots"
[4]: logs/test_report.log "Log da validação oficial"

# Findings — ZIA-TRADER v17

Atualizado em 2026-10-08. Este registro contém gaps verificados que não foram alterados para preservar as restrições do prompt, além do escopo concluído nas fases abaixo. Não é uma declaração de ausência de outros defeitos.

| Arquivo/linha | Evidência observada | Correção sugerida (aguarda revisão/aprovação) |
| --- | --- | --- |
| `infra/redis_cache.py:94-105` | Se Redis não conecta na criação do objeto, `RedisCache` usa `_InMemoryFallback`, que é apenas local ao processo. Isso não é estado compartilhado entre API e worker. | Em modo de produção/autonomia, bloquear a inicialização em qualquer processo sem Redis persistente e uniformizar health checks/fail-closed em todos os serviços. Não trocar o backend de locks sem ensaios de concorrência. |
| `core/reconciliation.py::_cached_intent/_cache_intent` | Cache de intenção é consultado como apoio; a tabela de intents é consultada primeiro e o fluxo depende do Redis apenas para dados transitórios/locks. | Formalizar por RFC quais campos são authoritative no PostgreSQL e quais são cache; executar testes de falha Redis/DB antes de alterar recuperação ou retry. |
| `core/manager.py:107-115`; `config/settings.py:30` | A ativação do kill switch atualiza a configuração do objeto em memória e registra evento persistente; não há evidência nesta fase de leitura de um estado único compartilhado após restart/entre processos. | Definir e revisar armazenamento atômico durável do estado do kill switch, carregamento no startup e consistência com cada adapter; manter fail-closed e cobrir restart/falhas antes de mudar código. |
| `docs/DATABASE_OPERATIONS.md` (TimescaleDB) | Hypertable opcional está implementada apenas para `market_candles`, desativada por padrão; a extensão não está disponível no serviço PostgreSQL padrão do Compose. | Validar em instância TimescaleDB de teste, medindo migração, constraint de candle e downgrade/restore antes de ativar a flag. |
| PostgreSQL/ambiente externo | A sandbox local não tem serviço PostgreSQL, VPS ou exchange; o backend é validado com SQLite local e PostgreSQL via CI, sem ensaio de deployment real. | Antes de deploy, ensaiar backup/restore, migrações e reconciliação em ambiente isolado semelhante à VPS e validar broker Demo/Testnet. |

Nas Fases 1–4, nenhuma lógica de sinais, cálculo de risco, sizing ou execução foi alterada. A Fase 5 adiciona resiliência de reconciliação e consulta read-only de ordens, sem mudar sinais, indicadores, sizing ou limites de risco. Nenhuma conexão real a broker/exchange, teste de mainnet ou execução de ordem foi feita; as flags live permanecem desligadas.

## Fase 2 — ingestão e integridade de feeds (2026-10-05)

- **Corrigido:** `MultiTimeframeFeed` agora valida OHLCV, ordenação, duplicatas, timestamps futuros, gaps em sessão e staleness antes de devolver o histórico. Histórico primário inválido segue o `FeedUnavailable` existente e não chega ao restante do ciclo de análise.
- **Corrigido:** eventos ativos/resolvidos são registrados em `data_gaps`; snapshots de order book com depth real são persistidos com intervalo mínimo e retenção configuráveis.
- **Observabilidade:** snapshots expõem idade, cobertura, cadência e contagem de gaps em `data_quality`; erros de timeframe secundário continuam explícitos.
- **Limitação mantida:** não foi conectado calendário oficial de feriados/DST para B3/Forex. Gaps históricos entre sessões não são inferidos; staleness do último candle é o controle fail-closed para parada atual do feed.
- **Limite de escopo:** adapters de ordens, engine de decisão/sinais, cálculo de risco, sizing, kill switch, idempotência e reconciliação não foram editados.

## Fase 3 — MLOps e validação temporal (2026-10-06)

- **Implementado:** treino controlado com seed/hash, walk-forward past-only, purge/embargo, blocos OOS não sobrepostos, métricas por regime, baselines líquidos de custos/slippage, Brier/ECE e reliability curve.
- **Implementado:** registry existente integrado à promoção/rollback; métricas são persistidas em `model_metrics`; a entrada legada `ai/train_ensemble.py` delega ao fluxo controlado.
- **Implementado:** monitor invocável de PSI e degradação de performance; ao cruzar limites, emite alerta, grava `drift_status.json`, tenta restaurar backup e mantém predição em `hold` até revisão manual.
- **Implementado:** Transformer usa `batch_first=True` internamente com shape público preservado e equivalência numérica coberta por teste.
- **Limitação de dados:** não havia dataset OHLCV de procedência verificada no checkout. Nenhum treino real, métrica de mercado ou promoção foi executado; os resultados e pressupostos estão em `docs/reports/phase3_status.md`.
- **Limitação operacional:** monitoramento de drift é invocável, não está agendado, e depende de dados recentes rotulados. Custos padrão são pressupostos ajustáveis; short não inclui borrow/funding. O Sharpe proxy legado ainda usa `sqrt(252)` sem conhecer o timeframe.
- **Limite de escopo:** `core/engine.py`, features de produção, sinais, sizing, risco, execução, kill switch, idempotência e reconciliação não foram editados.

## Fase 4 — performance e paridade live/backtest (2026-10-07)

- **Implementado e validado localmente:** retries idempotentes limitados, backoff exponencial com jitter, `Retry-After` numérico limitado, circuito por provider e offload com timeout da chamada síncrona Forex read-only. O fallback de timeout não encerra necessariamente a thread subjacente; conferir `infra/async_http.py:200-225`. Se o provider não respeitar seu timeout, usar API assíncrona com timeout nativo ou isolamento de worker limitado antes da produção.
- **Implementado e validado com fixture sintética:** cache de features/pullback com append-only e equivalência numérica aos caminhos canônicos. Frames corrigidos, dados inválidos e janelas deslizantes fazem fallback a recálculo integral por correção. Assim, snapshots idênticos e históricos append-only evitam rebuild; feeds live de tamanho fixo ou candle corrente mutável podem continuar recalculando.
- **Corrigido com aprovação explícita do usuário (2026-10-08):** o guard de warm-up do cache em `core/pullback_strategy.py` foi alinhado ao primeiro prefixo aceito pelo cálculo canônico, sem alterar `calculate_pullback_signal` ou seus critérios. A regressão `tests/test_phase4_parity.py::test_pullback_cache_matches_canonical_at_warmup_boundary` verifica que, com `ema_period=50` e 52 barras, ambos retornam `candidate_action="buy"` e `action="hold"`; a comparação inclui a primeira posição válida. Nenhum método de ordem/execução foi alterado.
- **Paridade limitada:** `tests/test_phase4_parity.py` usa candles determinísticos sintéticos. O teste compara somente o cálculo de sinal candle-only e estados/indicadores de cache; não prova paridade de order-flow, notícias, IA, risk gates, execução, broker ou dados de mercado reais. Confirmar com dataset verificado e Demo/shadow.
- **Nenhum método de ordem, cálculo de risco, sizing, kill switch, idempotência, reconciliação ou fórmula canônica de sinal foi alterado.** O escopo e os resultados medidos constam em `docs/reports/phase4_status.md`.

## Fase 5 — robustez do broker (2026-10-08)

- **Corrigido:** ao encontrar intent persistida como `submitted`, `pending`, `open` ou `partially_filled`, o reconciliador consulta a exchange por `clientOrderId` antes de reutilizar a intent; o estado remoto e o exchange order ID são persistidos, inclusive para fills parciais/terminais.
- **Corrigido:** `reconcile()` varre as intents abertas após restart; respostas confirmadas atualizam o estado local. Estado remoto ausente, divergente ou desconhecido é reportado como recuperação pendente/atenção. O auto-start do FastAPI não cria tasks e registra erro se a reconciliação não está `ok`; starts manuais retornam HTTP 503 antes de criar a task.
- **Fail-closed:** exceção de transporte sem confirmação remota deixa a intent em `submitted`, registra o erro e retorna `recovery_pending`, sem retry automático. Respostas explícitas de erro do adapter mantêm o retry limitado existente com o mesmo client ID.
- **Consulta Binance:** foi adicionada consulta assinada somente de leitura por `origClientOrderId` em `/v3/order`, propagada por `ExchangeConnector` e `MarketConnector`. O caminho foi validado por `FakeSession`; nenhuma requisição real à Binance foi feita.
- **Suíte de falhas:** cobre timeout com aceitação remota, timeout ambíguo, restart com `submitted`, sweep na reconciliação, fill parcial, reuso sem duplicidade, bloqueio pré-start, consulta do adapter e reconexão do WebSocket existente. A reconexão exercitada é somente a do dashboard FastAPI (`/ws/dashboard`).
- **Limitação confirmada:** não há implementação de WebSocket da exchange no código atual; portanto a reconexão de stream do broker não foi implementada nem validada. Também foi observado que `BinanceMainnetAdapter.place_order` não recebe/propaga `client_order_id`; fora do escopo Demo/Testnet, isso permanece sem correção. Manter `LIVE_TRADING_ENABLED=false` e `LIVE_MODE=false` até revisão e teste específicos.
- **Intervenção operacional:** quando a consulta por ID e a lista de ordens abertas não confirmam o estado, a intent continua pendente e o motor não inicia; é necessária reconciliação/manual review, não um reenvio automático.

## Revisão do modelo de negociação (2026-10-08)

- **Artefatos/inferência:** `models/` está vazio no checkout e `NEURAL_MODELS_ENABLED` é `false` por default. Sem um Ensemble treinado ou pesos neurais carregados, `RoboTraderUnified` forma `final_action="hold"`; o `MarketSignal` técnico é um gate de concordância, não uma rota alternativa para gerar entrada. Volumes externos em VPS não foram inspecionados. Não houve treino com dataset de procedência verificada.
- **Reconciliação do worker — alta prioridade:** `OrderReconciler.reconcile()` retorna `attention` para intents cuja recuperação não foi confirmada. O `worker.py` bloqueia somente `status == "error"` (e apenas se autonomia estiver ligada), portanto pode iniciar o motor com status `attention`; o Compose VPS usa este worker para rodar os motores. A API FastAPI, ao contrário, exige `status == "ok"`. Fechar a divergência e testar o startup do worker antes de autonomia/Demo.
- **Sniper/ordens — alta prioridade:** `worker.py` respeita `SNIPER_ENABLED`, mas os starts da API e o auto-start do FastAPI não consultam a flag. O `SniperEngine` recebe `OrderManager`, mas envia a entrada diretamente por `ExecutionEngine.execute_order`, fora do modo manual/confirmador do OrderManager. Unificar os gates e testes de aprovação antes de habilitar autonomia.
- **Limites declarados:** `WEEKLY_LOSS_LIMIT_PERCENT` e `MONTHLY_LOSS_LIMIT_PERCENT` aparecem na configuração/CLI, mas não foram encontrados no cálculo de runtime; os guards observados cobrem limite diário e drawdown. `ADAPTIVE_KELLY_ENABLED` default true, mas os chamadores live não fornecem `trade_returns`, pré-condição de pelo menos 20 amostras em `RiskAI.validate_order`. Não tratar esses controles como efetivos sem correção/teste.
- **Escala do score protegido:** os pesos de `calculate_market_signal` somam 1,10, enquanto o score depois é clamped em [-1, 1]. Verificar intenção e efeito sobre threshold/confidence; nenhuma fórmula foi alterada.
- O relatório detalhado, comparação por camada e checklist estão em `docs/reports/revisao_modelo_negociacao_2026-10-08.md`.

- **Interpretação de AUTO_START:** `AUTO_START_ENGINES=false` é aplicado pelo lifespan do FastAPI, mas `worker.py` sempre inicia o motor principal; no Compose VPS, esse processo dedicado executa os motores. Com autonomia desligada isto não habilita ordens, mas o flag não significa que todos os loops estejam parados. Documentar/alinhar a semântica antes do deploy.

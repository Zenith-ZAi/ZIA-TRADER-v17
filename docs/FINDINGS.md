# Findings — ZIA-TRADER v17

Atualizado em 2026-10-06. Este registro contém gaps verificados que não foram alterados para preservar as restrições do prompt, além do escopo concluído nas fases abaixo. Não é uma declaração de ausência de outros defeitos.

| Arquivo/linha | Evidência observada | Correção sugerida (aguarda revisão/aprovação) |
| --- | --- | --- |
| `infra/redis_cache.py:94-105` | Se Redis não conecta na criação do objeto, `RedisCache` usa `_InMemoryFallback`, que é apenas local ao processo. Isso não é estado compartilhado entre API e worker. | Em modo de produção/autonomia, bloquear a inicialização em qualquer processo sem Redis persistente e uniformizar health checks/fail-closed em todos os serviços. Não trocar o backend de locks sem ensaios de concorrência. |
| `core/reconciliation.py:58-73, 93-97` | Cache de intenção é consultado como apoio; a tabela de intents é consultada primeiro e o fluxo depende do Redis apenas para dados transitórios/locks. | Formalizar por RFC quais campos são authoritative no PostgreSQL e quais são cache; executar testes de falha Redis/DB antes de alterar recuperação ou retry. |
| `core/manager.py:107-115`; `config/settings.py:30` | A ativação do kill switch atualiza a configuração do objeto em memória e registra evento persistente; não há evidência nesta fase de leitura de um estado único compartilhado após restart/entre processos. | Definir e revisar armazenamento atômico durável do estado do kill switch, carregamento no startup e consistência com cada adapter; manter fail-closed e cobrir restart/falhas antes de mudar código. |
| `docs/DATABASE_OPERATIONS.md` (TimescaleDB) | Hypertable opcional está implementada apenas para `market_candles`, desativada por padrão; a extensão não está disponível no serviço PostgreSQL padrão do Compose. | Validar em instância TimescaleDB de teste, medindo migração, constraint de candle e downgrade/restore antes de ativar a flag. |
| PostgreSQL/ambiente externo | A sandbox local não tem serviço PostgreSQL nem VPS/exchange; validação PostgreSQL é definida no CI, ainda depende da execução remota dos novos checks. | Aguardar CI verde e, antes de deploy, ensaiar backup/restore e migrações em ambiente isolado semelhante à VPS. |

Nenhuma lógica de sinais, cálculo de risco, envio de ordem, idempotência ou reconciliação foi alterada neste refinamento. Não foi feita conexão a broker/exchange, teste de mainnet ou execução de ordem real.


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
- **Implementado e validado com fixture sintética:** cache de features/pullback com append-only e equivalência numérica aos caminhos canônicos. Revisões do candle, dados inválidos e janelas deslizantes fazem fallback a recálculo integral por correção. Assim, snapshots idênticos e históricos append-only evitam rebuild; feeds live de tamanho fixo ou candle corrente mutável podem continuar recalculando.
- **Divergência não corrigida — requer aprovação humana:** `core/pullback_strategy.py:368-371`. O cache aguarda um candle a mais que `calculate_pullback_signal` antes de calcular o candidato. Evidência reproduzível: `tests/test_phase4_parity.py::test_pullback_cache_warmup_divergence_is_explicitly_preserved` — com `ema_period=50` e prefixo de 52 barras, o cálculo direto dá `candidate_action="buy"`, o cache dá `candidate_action="hold"`; ambos dão `action="hold"`. Ajustar `index` para alinhar a fronteira pode mudar candidato/telemetria na borda do gate; não foi feito sem aprovação.
- **Paridade limitada:** `tests/test_phase4_parity.py` usa candles determinísticos sintéticos. O teste compara somente o cálculo de sinal candle-only e estados/indicadores de cache; não prova paridade de ordem-flow, notícias, IA, risk gates, execução, broker ou dados de mercado reais. Confirmar com dataset verificado e Demo/shadow.
- **Nenhum método de ordem, cálculo de risco, sizing, kill switch, idempotência, reconciliação ou fórmula canônica de sinal foi alterado.** O escopo e os resultados medidos constam em `docs/reports/phase4_status.md`.

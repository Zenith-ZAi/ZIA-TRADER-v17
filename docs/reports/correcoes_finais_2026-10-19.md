# Correções finais de segurança, risco e MLOps — 2026-10-19

## Resumo executivo

Esta etapa continua o refinamento de Fases 1–5 e implementa as correções finais descritas no prompt de implementação. O escopo foi limitado a autorização/lifecycle, centralização de ordens, contratos de dados e modelos, observabilidade de drift e testes. **As fórmulas do `MarketSignal`, indicadores, regras de pullback, alvo de treinamento e parâmetros financeiros de risco não foram alterados.** Os pesos de modelos foram alinhados à combinação que o runtime já usava antes da centralização (Transformer 0,30; LSTM 0,30; Ensemble 0,40), não recalibrados por desempenho histórico.

A conclusão desta etapa **não equivale a autorização para operar**. O repositório não possui um ledger de equity/trades que comprove completude, custos, funding, fluxos externos e timestamps; os métodos de consulta verificada retornam `None` deliberadamente. Por isso, novas entradas no caminho de execução ficam fail-closed. O modo de negociação real continua indisponível e as flags `LIVE_TRADING_ENABLED`, `LIVE_MODE`, `AUTONOMOUS_TRADING_ENABLED`, `MANUAL_TRADING_ENABLED`, `AUTO_START_ENGINES`, `NEURAL_MODELS_ENABLED` e `BACKTEST_USE_ENSEMBLE` permanecem explicitamente desligadas nos exemplos/Compose.

## Estado das fases

| Etapa | Estado observado |
|---|---|
| Fases 1–3 | Integradas anteriormente: migrações/backup, qualidade e persistência de feed, walk-forward, registry e drift. |
| Fase 4 | PR #14 integrada: resiliência HTTP e caches incrementais; warm-up do cache alinhado à implementação canônica. |
| Fase 5 | PR #15 integrada: recuperação de intents `submitted` por identificador do cliente, reconciliação fail-closed e testes com mocks. Não há implementação de WebSocket de exchange; limitações do adapter mainnet seguem registradas em `docs/FINDINGS.md`. |
| Correções finais | Nesta branch: gates comuns para API/worker/Sniper, OrderManager como caminho de execução, contratos de ledger e Kelly, voto de modelos e scheduler opt-in de drift. Aguarda revisão/CI da PR desta etapa antes de integração. |
| VPS Shadow/Demo | **Preparação condicional**, não homologação operacional. Ainda dependente de fonte real de risco/dados, validação da composição no host VPS e exercício controlado de Demo/Testnet. |

## 1. Lifecycle e centralização da execução

O worker e o lifespan da API respeitam `AUTO_START_ENGINES`; com o flag falso, os processos podem disponibilizar infraestrutura/API, mas não iniciam os loops de negociação. O auto-start e os starts explícitos passam pelo checkpoint de reconciliação, que só libera engines quando o estado é exatamente `ok`; `attention`, erro, exceção ou resposta incompleta bloqueiam o start.

`SNIPER_ENABLED` é agora gate no helper da API, em `TradingManager` e no próprio `SniperEngine`. Entradas e saídas geradas pelos motores passam pelo `OrderManager`, em vez de chamar uma rota alternativa de `ExecutionEngine`. A API não aceita `source` ou `confirmed` fornecidos no JSON como prova de autorização; o OrderManager revalida autorização, saldo, risco e reconciliação no momento da confirmação manual. O teste de confirmação manual usa dependências fake e habilitação explícita apenas no fixture; isso não muda o default operacional.

**Limitação operacional de saída:** o caminho automatizado de saída do motor também requer `AUTONOMOUS_TRADING_ENABLED=true`; os loops ficam inativos com `AUTO_START_ENGINES=false`, e não foi identificado um endpoint de fechamento manual independente que dispense essa flag. Não implantar com posições abertas sem um procedimento externo e testado de proteção/fechamento. A existência da classe OCO, por si só, não demonstra que ordens de proteção estão instaladas, reconciliadas ou executáveis no adapter escolhido.

## 2. Matriz de risco: configuração, consumidor e estado

Os percentuais abaixo são os valores versionados em `config/settings.py`; **não foram aumentados nem recalibrados** nesta etapa. A efetividade deve ser distinguida da mera configuração.

| Controle | Valor configurado | Consumidor/condição | Persistência e teste | Estado efetivo |
|---|---:|---|---|---|
| Confiança mínima | 0,70 | Agregador de modelos e gates de inferência; aplicado a sinais de IA (não inventado para ordem humana). | `tests/test_model_voting.py`, `tests/test_model_pipeline.py`. | Ativo como gate. Confiança baixa resulta em `HOLD`. |
| Risco máximo por trade | 2% | `RiskAI` calcula sizing a partir de saldo, preço/stop e limites; saídas usam validação separada. | `tests/test_risk_ai.py`, `tests/test_risk_exchange_balance.py`, `tests/test_stress.py`. | Configurado; tamanho não aumenta por falta de Kelly. Entradas de execução também dependem do ledger abaixo. |
| Stop-loss / take-profit | 2% / 5% | Políticas de posição e construção da ordem de entrada. | Testes de execução/backtest; persistência de estado. | Valores mantidos. A colocação/execução real de OCO precisa de homologação do adapter e reconciliação. |
| Exposição por símbolo | 10% | `RiskAI` verifica exposição persistida antes de expandir. | `tests/test_risk_exchange_balance.py`, `tests/test_stress.py`. | Configurado e testado em cenários simulados; fonte de posição deve permanecer sincronizada com exchange. |
| Exposição total | 30% | `RiskAI` agrega posições persistidas. | `tests/test_risk_exchange_balance.py`. | Configurado e testado; não equivale a prova de consistência entre processos/adapters. |
| Perda diária | 5% | Agora exige período `daily` no snapshot UTC completo e atualizado antes de uma entrada de execução. | `tests/test_risk_period_kelly_contract.py`, inclusive gatilho diário. | **Fail-closed:** `DatabaseManager.get_verified_risk_periods()` retorna `None`; nenhuma entrada de execução é liberada por esse contrato ainda. |
| Perda semanal | 10% | Snapshot UTC `weekly`, com equity inicial e P&L realizado + não realizado. | Testes abaixo/no limite e snapshot inválido/stale. | **Fail-closed** até implementação do ledger verificável. |
| Perda mensal | 15% | Snapshot UTC `monthly`, com os mesmos requisitos de integridade. | Testes de limite mensal e snapshot inválido/stale. | **Fail-closed** até implementação do ledger verificável. |
| Drawdown/circuit breaker | 15% | `evaluate_circuit_breaker` compara saldo e capital inicial; combina com P&L diário disponível. | `tests/test_upgrade_core.py`, `tests/test_risk_ai.py` e testes de gates. | Lógica determinística mantida. O circuito não substitui o ledger; sua implantação depende de capital inicial e saldos confiáveis. |
| Kelly adaptativo | Fração 0,25; mínimo 20 trades; idade máx. 365 dias; risco máximo continua limitado a 2%. | `RiskAI` consulta apenas `get_verified_trade_returns()`, ignora listas fornecidas pelo chamador e valida IDs únicos, timestamps UTC, ordem cronológica e retornos finitos. | `tests/test_risk_period_kelly_contract.py`: 19/20/21 amostras, spoof, duplicata, cronologia, stale/futuro e restart. | **Sem efeito adaptativo em produção:** a fonte persistente retorna `None`; não são fabricadas amostras. |
| Filtros da Binance | `LOT_SIZE`, `PRICE_FILTER`, `MIN_NOTIONAL`/`NOTIONAL` | Adapter busca filtros e arredonda quantidade/preço para baixo, rejeitando minQty e notional mínimo conhecidos. | `tests/test_binance_adapter.py`. | Parcialmente coberto em mock. Máximos, filtros específicos de ordem a mercado e comportamento de cada adapter ainda exigem Testnet/Demo. |
| Custos | Custos/fricção configurados no backtest e nos contratos do modelo. | Treino/drift reportam métricas líquidas segundo a premissa de custos configurada; ledger futuro deve incluir comissões/funding. | Testes de treino/drift/backtest. | Não há prova de custos realizados na fonte de P&L operacional. |
| Consistência entre processos/restart | Settings/DB/Redis conforme configuração de deploy. | Reconciliação antes do start; snapshots devem identificar conta/período/frescor e sobreviver a restart. | `tests/test_final_safety_gates.py`, `tests/test_phase5_broker_resilience.py`, `tests/test_e2e_resilience.py`. | Coberto com SQLite/mocks; ainda não homologado em PostgreSQL/Redis do VPS com exchange Demo. |

As tabelas SQL `DailyPNL`, `WeeklyPNL` e `MonthlyPNL` guardam somente agregados básicos; não comprovam origem, completude, taxas/funding, fluxos externos, equity inicial de período ou horário de atualização. Por isso, não são tratadas como ledger de risco. **Antes de habilitar ordens é necessário implementar e validar a origem `equity_ledger_v1` para os três períodos e a origem `closed_execution_ledger_v1` para Kelly**, incluindo reconciliação com fills e resultados após custos. A indisponibilidade atual é um bloqueio intencional, não uma autorização para assumir P&L zero.

## 3. Contrato, voto e inferência de modelos

O contrato de features é versionado e conserva a ordem e as fórmulas existentes. A carga do Ensemble requer versão ativa no registry, correspondência do hash e compatibilidade de schema/labels/metadata. Saídas probabilísticas com shape, valores ou normalização inválidos são rejeitadas; não se fabricam probabilidades quando o Ensemble não está treinado.

`core/model_voting.py` é a fonte única do voto. Os pesos finitos e não negativos devem somar 1; somente modelos prontos são incluídos e os pesos são renormalizados pelo peso disponível. O mínimo de cobertura é 0,40: Transformer ou LSTM isolados (0,30 cada) não bastam; o Ensemble isolado (0,40) pode satisfazer a cobertura se aprovado. Ausência de modelo não é voto neutro. Desacordo buy/sell, empate, output/versão inválida e confiança abaixo de 0,70 geram `HOLD`. O relatório contém estados e versões dos votantes; o HOLD persistente por drift prevalece sobre qualquer voto.

O backtest usa a mesma política quando `BACKTEST_USE_ENSEMBLE=true`; se o artefato aprovado faltar, retorna `model_unavailable` e zero trades, em vez de executar sem o filtro solicitado. Com o flag falso, o backtest continua sendo um replay da estratégia técnica, não evidência de paridade com a decisão de IA em runtime.

A pasta `models/` está presente, mas não contém arquivos no checkout auditado. Não foi apresentado dataset OHLCV de produção com procedência verificada; portanto não houve novo treino nem promoção. O pipeline registra hash e período da origem, schema/regras de rótulo, configurações e métricas walk-forward/após custos. Transformer e LSTM não são treinados pelo pipeline walk-forward existente e continuam explicitamente desligados até haver dados, benefício demonstrável, treino independente e artefatos aprovados.

## 4. Monitoramento de drift

O avaliador acrescenta distribuição de classes e performance líquida de custos à avaliação existente, registra incidentes persistentes e conserva HOLD para revisão manual. O scheduler processa cada hash novo de dataset uma vez, aguarda maturidade/volume mínimo de rótulos e persiste estado/relatório; ele não coleta dados, não treina, não promove e não autoriza execução.

No `docker-compose.vps.yml`, `model-drift-monitor` está isolado no perfil opt-in `model-monitor`, recebe CSV configurável, gravador de relatório persistente e flags de negociação/live desligadas. O perfil **não foi iniciado** e o caminho de dataset de exemplo não constitui uma fonte de produção. Não habilitar o monitor até validar timezone/ordenamento do CSV, atraso de labels, amostra mínima, custo realista e alertas operacionais no host de destino.

## 5. Segurança, flags e escopo

- `.env.vps.example` e Compose mantêm `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `AUTONOMOUS_TRADING_ENABLED=false`, `MANUAL_TRADING_ENABLED=false`, `AUTO_START_ENGINES=false`, `NEURAL_MODELS_ENABLED=false` e `BACKTEST_USE_ENSEMBLE=false`; o drift monitor também desliga essas capacidades.
- Nenhuma credencial real foi adicionada ao repositório; esta revisão não leu arquivos `.env` locais, não conectou a corretora, não executou ordem nem usou conta real.
- Nenhuma regra de sinal técnico/indicadores, pullback, stop/take-profit ou percentual de risco foi alterada. O ajuste de `ENSEMBLE_WEIGHTS` remove a divergência de configuração e conserva a ponderação que o runtime já aplicava (`0,30/0,30/0,40`).
- O teste da confirmação manual foi atualizado para habilitar manualmente o modo apenas dentro do fixture e usar dependências fake saudáveis; os testes não são autorização de negociação.

## 6. Validação executada nesta sessão

Baseline no master remoto `62f3182`:

```text
142 passed, 3 skipped
```

Após as alterações desta branch, `python -m compileall -q .` e `git diff --check` passaram; a suíte completa terminou com:

```text
178 passed, 3 skipped, 1 warning
```

São 36 testes aprovados a mais que a baseline, sem redução no total de 3 skips. O warning é um `PendingDeprecationWarning` de `starlette` sobre `python_multipart`. Os testes utilizam SQLite, mocks e dados sintéticos; não representam validação de exchange Demo/Testnet ou PostgreSQL remoto.

O arquivo `docker-compose.vps.yml` passou por parsing YAML. Não foi possível executar `docker compose config` porque o executável Docker não está instalado nesta sessão; o Compose ainda precisa ser validado no VPS ou em CI com Docker disponível.

## 7. Bloqueios antes de Demo e VPS

1. Implementar o ledger verificável de equity diário/semanal/mensal e o ledger de execuções fechadas, com fees, funding, fluxo externo, timestamps UTC, consistência multi-processo e reconstrução após restart. Até lá, entradas executadas serão rejeitadas.
2. Definir e testar como um operador fecha uma posição existente quando autonomia/auto-start estão desligados; não usar o desligamento dos loops como substituto de proteção de posição.
3. Validar stop/take/OCO e cancelamento da proteção oposta no adapter escolhido, especialmente em cancelamento parcial, timeout e restart. Manter pendência de WebSocket da exchange e suporte `client_order_id` no adapter mainnet documentada; não usar mainnet.
4. Obter dataset OHLCV com procedência, completude e labels maduros; executar validação temporal independente, registrar artefato no registry e revisar métricas líquidas de custos antes de habilitar qualquer modelo.
5. Executar CI remota da PR, validar Compose com Docker, migrar PostgreSQL 16, testar backup/restore e exercitar reconciliação em Testnet/Demo com zero risco financeiro real.
6. Só após esses passos considerar perfil Shadow/Demo controlado. Esta entrega **não declara o sistema pronto para negociação real nem para uso autônomo em produção**.

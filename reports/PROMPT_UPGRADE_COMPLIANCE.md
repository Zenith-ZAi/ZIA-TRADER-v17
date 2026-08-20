# Relatório de Upgrade do Core e do Backend

**Projeto:** ZIA-TRADER-v17
**Prompt auditado:** `PromptdeUpgrade.txt`
**Data:** 20 de agosto de 2026
**Modo:** simulação/shadow; nenhuma ordem foi enviada durante o upgrade.

## Resumo executivo

O upgrade implementou as oito lacunas críticas descritas no prompt, com uma distinção importante: funcionalidades que dependem de uma corretora Forex real continuam **fail-closed** até que exista um broker específico, suas credenciais e seus contratos de execução sejam validados. O caminho Binance continua sendo o default, e o caminho Forex novo funciona somente em modo paper determinístico por padrão.

As alterações foram feitas sem reestruturar a stack existente. O console Rich permanece compatível, o FastAPI continua sendo o entrypoint web, o TradingManager continua orquestrando os motores e o banco SQLAlchemy permanece como persistência principal.

## Conformidade com o checklist

| Lacuna do prompt | Implementação aplicada | Estado |
|---|---|---|
| Orquestração do menu | `RuntimeConfigRegistry` lê `StrategyConfig` e `AlgorithmConfig`, aplica timeframes, stop, alvo, risco e confluência ao `Settings`; `TradingManager.reload_runtime_config()` atualiza os motores | Implementado para estratégias e algoritmos |
| Matriz multi-timeframe | `core/multi_timeframe.py` calcula sinais por timeframe e exige confirmações mínimas; configuração `ANALYSIS_TIMEFRAMES` e `MULTI_TIMEFRAME_MIN_CONFIRMATIONS` | Implementado no motor live, desligado por default |
| Intervalo 10m | Binance não fornece 10m nativo no adapter; o código busca 5m e agrega OHLCV causalmente em blocos de 10 minutos | Implementado e testado |
| Notícias fail-closed | `core/news_gate.py` verifica provedores saudáveis, quantidade de artigos, frescor e choque de sentimento; entradas sem contexto suficiente são bloqueadas quando o flag está ativo | Implementado, ativo por default para entradas |
| Circuit breaker | `core/risk_guard.py` bloqueia novas entradas quando drawdown relativo ao capital inicial ou perda diária excede limites | Implementado e ativo por default |
| Emergency Exit | O motor principal e o Sniper reconhecem gatilhos de evento e choque de notícia; a saída automática permanece desligada por default para evitar comportamento não validado | Implementado como recurso opt-in |
| Estado persistente | Nova tabela `runtime_position_state`, Redis com indicador de persistência e reconciliação de posições no início do motor | Implementado; Redis persistente é obrigatório quando autonomia está ativa |
| Dashboard/API | CORS restrito, `/dashboard/status`, `/runtime/reload`, `/ws/dashboard` autenticado e `/admin/dashboard` com status runtime | Implementado como superfície backend; frontend visual ainda não foi criado |
| Spread/slippage/payout | `core/microstructure.py` calcula spread em bps, slippage estimado, custo de ida e volta e reward/risk ratio; RiskAI e Sniper rejeitam custos fora dos limites | Implementado |
| Forex | `ForexPaperAdapter` funcional para testes; `ForexLiveAdapter` rejeita conexão/ordem até broker específico ser configurado | Implementado com segurança, não é conexão live |

## Parâmetros refinados

Os novos defaults foram escolhidos para preservar segurança e não para aumentar artificialmente o número de trades. A matriz multi-timeframe usa `1m,5m,1h` como configuração declarada, mas `MULTI_TIMEFRAME_ENABLED=false` até que os dados e a execução por timeframe sejam validados. Quando ativada, exige duas confirmações.

O gate de notícias exige pelo menos um provedor saudável e um artigo utilizável por padrão. O circuit breaker bloqueia novas entradas a partir de drawdown de 15% em relação ao capital inicial ou do limite diário já configurado. O gate de microestrutura limita spread a 30 bps, slippage estimado a 20 bps e exige reward/risk mínimo de 1,2. Esses limites são parametrizados e não representam garantia de execução.

| Configuração | Default | Efeito |
|---|---:|---|
| `MULTI_TIMEFRAME_ENABLED` | `false` | Evita ativar MTF antes da validação específica |
| `ANALYSIS_TIMEFRAMES` | `1m,5m,1h` | Matriz declarada para análise live |
| `MULTI_TIMEFRAME_MIN_CONFIRMATIONS` | `2` | Confirmação mínima entre sinais |
| `NEWS_FAIL_CLOSED_FOR_ENTRY` | `true` | Sem contexto confiável, não entra |
| `NEWS_MIN_HEALTHY_PROVIDERS` | `1` | Disponibilidade mínima de fonte |
| `NEWS_MIN_ARTICLES_FOR_ENTRY` | `1` | Quantidade mínima de contexto |
| `CIRCUIT_BREAKER_MAX_DRAWDOWN_PERCENT` | `0.15` | Limite de bloqueio por drawdown |
| `EMERGENCY_EXIT_ENABLED` | `false` | Saída extraordinária exige ativação explícita |
| `MICROSTRUCTURE_GATE_ENABLED` | `true` | Verifica custo antes de validar ordem |
| `MIN_REWARD_RISK_RATIO` | `1.2` | Payout mínimo estimado |
| `REDIS_REQUIRED_FOR_AUTONOMOUS` | `true` | Impede autonomia com fallback em memória |
| `MARKET_ADAPTER` | `binance` | Mantém Binance como caminho padrão |
| `FOREX_MODE` | `paper` | Forex não envia ordens externas |

## Bateria de validação

A suíte final passou com **51 testes**, além da compilação Python e `git diff --check`. Permaneceram somente dois warnings não bloqueantes de dependências externas: o aviso de `python_multipart` do Starlette e o aviso de configuração do encoder Transformer.

O replay shadow usou 600 barras do dataset público BTCUSDT/1h, criou seis observações, terminou com ação `hold` e confirmou `orders_sent=0`. As chamadas de notícias que excederam o timeout foram tratadas como indisponibilidade; o gate fail-closed manteve a decisão conservadora.

| Validação | Resultado observado |
|---|---:|
| Testes automatizados | 51 passed |
| Replay shadow | 600 barras; 6 observações; 0 ordens |
| Backtest comparativo | 43.816 candles; 8 trades; 0,791390% de retorno; Sharpe 0,076263; drawdown -0,357246%; win rate 87,5% |
| Protocolo Binance público | 43.816 candles; 8 trades; PnL 95,2362069444; retorno 0,952362%; Sharpe 0,092807; drawdown -0,337662%; integridade do dataset aprovada |
| Stress de spoofing | 5/5 cenários filtrados |
| Sharpe acima de 1,0 | Não atingido |
| Tick protocol de 2,3 milhões de ticks | Não executado; o dataset disponível contém candles, não ticks, e nenhum dado foi inventado |

O protocolo de gaps e eventos usa cenários sintéticos derivados do dataset para testar comportamento de risco. Esses cenários não devem ser interpretados como desempenho histórico real. O resultado permanece abaixo do Sharpe 1,0 e não justifica capital real.

## Latência

O benchmark local com 50 repetições em 600 candles apresentou o seguinte perfil. A decisão com Pullback recalculado continua sendo o gargalo principal; o cache reduz substancialmente o custo local.

| Componente | p50 | p95 |
|---|---:|---:|
| Features causais | 6,598620 ms | 9,577991 ms |
| Ensemble | 5,822006 ms | 8,558095 ms |
| Construção do Pullback cache | 75,124099 ms | 91,490011 ms |
| Sinal com Pullback | 52,779425 ms | 56,336641 ms |
| Sinal com Pullback cacheado | 4,572857 ms | 5,366160 ms |
| Decisão combinada sem cache | 66,805593 ms | 91,046011 ms |
| Decisão combinada cacheada | 17,501942 ms | 18,868152 ms |

As medições são somente do processo local. Não incluem rede, TLS, roteamento, fila, WebSocket, confirmação de saldo, matching engine, slippage efetivo ou tempo de preenchimento.

## Limitações remanescentes

O menu agora influencia estratégias e algoritmos quando as tabelas administrativas estão disponíveis, mas as credenciais criptografadas de `ExchangeConfig` ainda não são copiadas automaticamente para variáveis de ambiente nem usadas para trocar corretoras em runtime. Essa decisão evita um fluxo inseguro de segredos; a seleção de uma corretora live deve continuar sendo uma operação explícita de infraestrutura.

O dashboard possui superfície REST/WebSocket autenticada, mas ainda não há frontend visual versionado. A matriz MTF está implementada no motor live e o intervalo 10m foi resolvido por agregação 5m; o backtest histórico continua exigindo um dataset por timeframe para validar MTF sem vazamento temporal.

O adapter Forex paper não representa rollover, margem, lote, spread variável, execução parcial, calendário de negociação ou regras de um broker real. O adapter live deliberadamente falha fechado. Não se deve alterar `FOREX_MODE=live` esperando conexão automática.

A saída emergencial está implementada como política opt-in. Ativá-la sem calibrar notícias timestamped, deduplicação, regime, liquidez e comportamento de gaps pode causar saídas excessivas. O código não força esse comportamento por default.

## Estado operacional recomendado

A configuração recomendada permanece:

```text
MARKET_ADAPTER=binance
BINANCE_MODE=simulated
AUTONOMOUS_TRADING_ENABLED=false
SHADOW_MODE_ENABLED=true
SNIPER_ENABLED=false
ALLOW_SHORT=false
MULTI_TIMEFRAME_ENABLED=false
EMERGENCY_EXIT_ENABLED=false
FOREX_MODE=paper
```

A próxima etapa segura é executar uma Sandbox supervisionada com Redis persistente, reconciliação de posições e falhas de rede injetadas. A promoção a capital real depende de validação temporal fora da amostra, operação prolongada sem divergência de estado e aprovação explícita do usuário.

## Referências

[1]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17 "Repositório oficial ZIA-TRADER-v17"
[2]: https://github.com/binance/binance-spot-api-docs "Documentação pública da Binance Spot API"

Este documento é uma auditoria técnica do software, não uma recomendação personalizada de investimento.

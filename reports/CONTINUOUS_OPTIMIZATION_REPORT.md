# Relatório do Protocolo Contínuo de Otimização

**Projeto:** ZIA-TRADER-v17
**Prompt:** `PromptContínuo.txt`
**Data:** 20 de agosto de 2026
**Modo:** histórico/shadow; nenhuma ordem foi enviada.

## Resumo executivo

O protocolo contínuo foi implementado e executado sem ativar autonomia. O backend agora possui uma camada explícita de métricas de risco, busca temporal de parâmetros, correlação de ativos, alocação long-only, controle de custos pelo book, feedback incremental de Sharpe, endpoint REST autenticado e script reproduzível dos Testes A-D.

O resultado não foi artificialmente otimizado. O dataset principal contém **43.816 candles BTCUSDT/1h de 2020 a 2024**. A janela mais recente de 12 meses disponível nesse dataset tinha 8.760 barras. O optimizer terminou em 21,96 segundos, sem timeout, mas todas as combinações da validação produziram somente um trade; por isso, com o limite de segurança de três trades, **nenhuma combinação foi elegível para promoção automática**. O Sharpe observado na validação não deve ser tratado como evidência estatística suficiente.

> O alvo de Sharpe maior ou igual a 1,0 é um critério de seleção, não uma métrica a ser forçada. O protocolo mantém o resultado negativo ou inconclusivo quando os dados não sustentam a conclusão.

## Melhorias implementadas

| Componente | Melhoria atualizada | Integração |
|---|---|---|
| `SharpeAnalyzer` | Sharpe anualizado, Sortino, Calmar, retorno anualizado, máximo drawdown e número de observações | Resultado do `BacktestEngine` |
| `StrategyOptimizer` | Grid search limitado por avaliações e tempo, separação cronológica treino/validação, top 10, penalização por drawdown e elegibilidade por número mínimo de trades | Uso por script e endpoint |
| `CorrelationManager` | Matriz de correlação, pares com baixa correlação absoluta, pesos long-only por pseudo-inversa de covariância e volatilidade | Relatório de portfólio |
| `CostAwareExecutor` | Spread em bps, slippage estimado, impacto, melhor janela observada e redução automática de quantidade | Motor principal e Sniper |
| `SharpeFeedback` | Recompensa incremental pela mudança do Sharpe e aviso de reotimização periódica | Cada trade do backtest |
| API | `GET /api/optimize_sharpe?asset_list=...` autenticado, sem ordens, com orçamento configurável | FastAPI |
| Script | `scripts/run_continuous_protocol.py` reproduz os Testes A-D e salva JSON | Dados públicos Binance |

O cost-aware já complementa o gate de spread/slippage existente. Antes da execução autônoma, a quantidade validada pelo RiskAI é limitada à profundidade permitida do primeiro nível do book. Se a quantidade ajustada cair a zero, a ordem é rejeitada. Em shadow e Sandbox, nenhuma dessas regras envia ordens por si só.

## Teste A — otimização de parâmetros em 12 meses

A janela usada foi o trecho mais recente disponível do dataset local, de 8.760 barras. O baseline da validação apresentou Sharpe 1,275065, retorno de 0,103768%, drawdown máximo de -0,040298% e apenas um trade. As melhores combinações encontradas foram essencialmente equivalentes porque o período de validação teve amostra muito pequena.

| Critério | Resultado |
|---|---:|
| Avaliações do optimizer | Limitadas por configuração; execução em 21,96 s |
| Timeout | Não |
| Trades da validação baseline | 1 |
| Sharpe da validação baseline | 1,275065 |
| Retorno da validação baseline | 0,103768% |
| Drawdown da validação baseline | -0,040298% |
| Combinações elegíveis com pelo menos 3 trades | 0 |
| Parâmetros recorrentes no topo | EMA 100; confiança 0,60; stop 1%; alvo 3% |

A configuração recorrente no topo não foi promovida automaticamente. O relatório do optimizer inclui `selection_warning` quando nenhuma combinação atinge o número mínimo de trades. Isso impede que uma métrica alta baseada em uma única observação seja confundida com robustez.

## Teste B — regimes de alta volatilidade

Os anos de 2020 e 2022 foram executados com os mesmos dados públicos, comparando baseline e parâmetros encontrados. O resultado é informativo, não uma aprovação de produção: houve somente dois trades em 2020 no baseline e um trade em 2022.

| Ano | Variante | Sharpe | Retorno | Drawdown | Trades |
|---:|---|---:|---:|---:|---:|
| 2020 | Baseline | 0,315502 | 0,031925% | -0,093479% | 2 |
| 2020 | Otimizada | 0,496822 | 0,224954% | -0,201471% | 3 |
| 2022 | Baseline | 0,586175 | 0,058777% | -0,035310% | 1 |
| 2022 | Otimizada | 0,586175 | 0,058777% | -0,035310% | 1 |

A variante de 2020 aumentou retorno e Sharpe, mas também aumentou o drawdown absoluto. Portanto, não há evidência de redução de drawdown em pelo menos 20%; esse objetivo do prompt **não foi atingido**.

## Teste C — redução de custos

O teste histórico de redução de custos não foi declarado aprovado. O dataset OHLCV público não contém snapshots históricos de bid/ask e profundidade do livro. Sem esses dados, não é possível calcular slippage médio antes/depois ou afirmar redução de 0,1% por trade sem fabricar observações.

O código operacional já suporta a medição quando snapshots reais forem fornecidos: `CostAwareExecutor` escolhe a observação com menor impacto, estima spread/slippage e reduz a quantidade. A próxima validação deve usar gravações reais de order book em Sandbox ou um dataset tick/order-book público.

## Teste D — correlação e diversificação

Foram solicitados dez ativos públicos Binance em candles de 1h. Na segunda execução, sete ativos foram obtidos integralmente: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT e DOGEUSDT. LTCUSDT falhou por timeout; LINKUSDT e AVAXUSDT retornaram HTTP 451. O protocolo registrou essas falhas e não preencheu os dados ausentes com séries sintéticas.

A correlação absoluta entre os sete ativos disponíveis não produziu pares abaixo de 0,30. Isso indica que a cesta observada permaneceu altamente correlacionada no período coletado; não há evidência de diversificação suficiente para recomendar alocação live.

| Ativo | Peso analítico |
|---|---:|
| BNBUSDT | 56,482992% |
| ETHUSDT | 24,435551% |
| SOLUSDT | 14,333303% |
| DOGEUSDT | 4,748154% |
| BTCUSDT, XRPUSDT, ADAUSDT | 0% |

Esses pesos são uma saída matemática long-only, não uma recomendação operacional. A carteira analítica apresentou Sharpe **-0,585064**, Sortino -0,561596, Calmar -0,563853, retorno anualizado -35,738880% e drawdown máximo -63,383277%. A recomendação é **não aplicar esses pesos em capital real**.

A simulação bootstrap de três meses teve Sharpe médio -0,559450, mediana -0,584566, percentil 5 de -3,960845 e percentil 95 de 2,623304. Esse intervalo amplo é uma projeção de cenário histórico, não uma previsão de mercado nem um sinal de negociação.

## Estado do backend e uso

O endpoint `GET /api/optimize_sharpe?asset_list=BTC/USDT,ETH/USDT` exige usuário trader autenticado, usa o timeframe configurado, respeita o orçamento do optimizer e retorna `orders_sent=0`. O endpoint não aplica automaticamente seus parâmetros ao runtime; a promoção continua sendo uma decisão administrativa explícita, após validação fora da amostra.

Os parâmetros principais estão no `.env.example`:

```text
RISK_FREE_RATE_ANNUAL=0.0
METRICS_PERIODS_PER_YEAR=252
OPTIMIZER_MAX_EVALUATIONS=32
OPTIMIZER_MAX_SECONDS=540
OPTIMIZER_VALIDATION_FRACTION=0.30
OPTIMIZER_MIN_TRADES=3
OPTIMIZER_REOPTIMIZE_EVERY=50
PORTFOLIO_LOW_CORRELATION_THRESHOLD=0.30
PORTFOLIO_MAX_WEIGHT=1.0
COST_AWARE_EXECUTION_ENABLED=true
MAX_BOOK_IMPACT=0.10
```

Para dados horários, o script usa `METRICS_PERIODS_PER_YEAR=8760`. O default 252 continua disponível para séries diárias. Essa separação evita misturar anualização diária com candles horários sem explicitar a hipótese.

## Validação final

A suíte completa terminou com **57 testes aprovados**, compilação Python e `git diff --check` sem erros. Permaneceram apenas dois warnings não bloqueantes de dependências externas: a recomendação do Starlette para `python_multipart` e o aviso do encoder Transformer.

Nenhuma ordem real, Demo, Testnet ou paper foi enviada pelo protocolo. A configuração de produção segura permanece com autonomia desligada, shadow ativo, short Spot proibido e Binance simulada como default.

## Recomendações e limitações

A recomendação imediata é manter o sistema em shadow/Sandbox e coletar pelo menos dezenas de trades por combinação antes de interpretar Sharpe, Sortino ou Calmar. A seleção automática está bloqueada quando a validação não atinge três trades. Também é necessário coletar order book real para concluir o Teste C e obter ativos adicionais ou uma janela comum para concluir o Teste D com dez séries.

O prompt solicita geração de alfa acima de benchmark e Sharpe projetado para três meses. O protocolo não declarou esses objetivos atingidos: não foi fornecido benchmark comparável no mesmo universo e a projeção Monte Carlo foi marcada apenas como cenário bootstrap. Não foram inventados dados para preencher essa lacuna.

## Referências

[1]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17 "Repositório oficial ZIA-TRADER-v17"
[2]: https://github.com/binance/binance-spot-api-docs "Documentação pública da Binance Spot API"

Este relatório é uma auditoria técnica de software e dados históricos, não uma recomendação personalizada de investimento.

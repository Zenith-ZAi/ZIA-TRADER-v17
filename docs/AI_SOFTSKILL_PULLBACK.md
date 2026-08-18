# Softskill da IA — Pullback Cirúrgico LTA/LTB

Esta política traduz o prompt de pullback em regras determinísticas auditáveis no ZIA-TRADER-v17. Ela não representa uma personalidade do modelo nem uma promessa de precisão; cada entrada continua sujeita a risco, dados válidos, custos de execução e validação fora da amostra.

## Camadas da decisão

| Camada | Regra implementada |
|---|---|
| Macro | EMA configurável, por padrão EMA 200: acima permite somente viés de compra; abaixo permite somente viés de venda |
| Meso | Dois pivôs de swing confirmados projetam linha de tendência dinâmica de suporte/resistência |
| Micro | Toque da linha, RSI 14 em zona de exaustão e volume do pullback abaixo de 80% da média de 20 |
| Gatilho | Rompimento do máximo/mínimo da barra de pullback, volume acima de 130% da média e cruzamento de RSI pela linha 50 |
| Risco | Stop de 1,5 ATR, alvo de 2,0 ATR e breakeven após 0,5 ATR |
| Calendário | Bloqueio padrão de 60 segundos antes e 300 segundos depois de evento econômico configurado |
| Execução | O sinal não envia ordem sozinho; precisa passar pelo modelo, confluência, saldo, exposição, RiskAI e flag autônoma |

A implementação está em [`core/pullback_strategy.py`](../core/pullback_strategy.py), é exposta no resultado de `MarketSignal` e é aplicada no backtest quando `PULLBACK_STRATEGY_ENABLED=true`. O filtro é causal: pivôs usam somente barras confirmadas e o gatilho usa a barra atual e o histórico anterior.

## Parâmetros

Os parâmetros ficam em `config/settings.py` e no `.env.example`. A estratégia foi configurada para funcionar em 5 minutos e 1 hora por meio do timeframe do coletor e da adaptação dos níveis pelo ATR; o período da EMA, RSI, ATR, volume e multiplicadores podem ser ajustados por ambiente.

## Fricção Sandbox

A camada [`execution/friction.py`](../execution/friction.py) modela latência de 150–500 ms, slippage de 0,5–2 ticks, spread, comissão de 0,05% e seed reprodutível. Ela é aplicada no backtest somente quando `FRICTION_ENABLED=true`. `FRICTION_SLEEP_ENABLED` permanece falso por padrão para não alongar testes; o custo continua contabilizado de forma determinística.

## Critérios de validação

Os números do anexo `PromptdeSandboxT.txt` — 214 trades, win rate 67,4%, retorno líquido 18,4%, drawdown 13,8% e Sharpe 1,24 — são tratados como **alegações não reproduzidas** neste checkout. Não há no repositório o dataset de cinco anos, o replay tick-a-tick, os dez eventos econômicos, os cinco cenários de spoofing nem o log completo que sustentaria esses números. Portanto, eles não foram promovidos para métricas oficiais.

Para aprovação futura, o relatório deve mostrar o dataset, janela temporal, número de barras/ticks, trades, custos, slippage, regime, drawdown por sessão, Sharpe líquido, duplicatas e todas as entradas bloqueadas por evento. Nenhum backtest com dados aleatórios ou números não rastreáveis deve ser usado como comprovação.

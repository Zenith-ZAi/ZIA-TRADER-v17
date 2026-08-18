# Homologação Binance Demo — ZIA-SandBox

> Validação técnica em ambiente Demo. Nenhuma ordem foi criada, cancelada ou alterada. Os resultados de mercado são um recorte de teste e não representam recomendação de investimento nem garantia de rentabilidade.

## Resultado executivo

O erro privado Binance `-2015` foi **corrigido** nesta tentativa. A nova configuração do pacote utilizava os aliases `BINANCE_DEMO_API_KEY`, `BINANCE_DEMO_SECRET_KEY` e `BINANCE_DEMO_BASE_URL`, sem `BINANCE_MODE`. O sistema foi ajustado para aceitar esses aliases, inferir `BINANCE_MODE=demo` quando `ENVIRONMENT=DEMO` e manter o host `demo-api.binance.com`.

A leitura privada de saldo foi aprovada. O Demo retornou dois ativos, `USDC` e `USDT`, sem que qualquer ordem fosse enviada.

## Conectividade e experiência de mercado

| Verificação | Resultado |
|---|---:|
| Ambiente | `demo` |
| Host | `demo-api.binance.com` |
| Conexão e sincronização | Aprovadas; 3.549 ms |
| Saldo privado | **Aprovado; 1.057 ms** |
| Ticker e bookTicker | Aprovados; 3.335 ms |
| Histórico | 500 candles de 1 minuto; 1.126 ms |
| Ordens enviadas | `0` |
| Ativos retornados | `USDC`, `USDT` |

O retorno privado confirma que a chave, o segredo, o ambiente Demo e a permissão de leitura estão coerentes. A validação não habilita `TRADE` e não homologa execução de ordens.

## Leitura de mercado e estratégia

| Métrica | Resultado |
|---|---:|
| Símbolo | `BTC/USDT` |
| Último preço observado | 64.725,39 USDT |
| Bid / ask | 64.725,39 / 64.725,40 |
| Ação candidata | `sell` |
| Ação final | `hold` |
| Status | `rejected` |
| Confiança | 0,5923 |
| Score | -0,18465 |
| Regime | Transição |
| Volatilidade ATR | 0,0002800 |
| Fluxo de volume | Neutro |
| Anomalia de volume | Não |

A estratégia identificou uma pressão vendedora candidata, mas **não autorizou a negociação** porque a confiança ficou abaixo do limiar operacional. Essa é a experiência estratégica esperada: o algoritmo distingue um viés de mercado de um sinal suficientemente confiável para virar ordem.

## RiskAI e sizing

O RiskAI bloqueou o sinal efetivo porque a ação final era `hold`, retornando `Símbolo ou ação inválidos`. Isso evita que um sinal rejeitado contorne a gate estratégica. Um caso hipotético de sizing, usado apenas para validar limites, calculou quantidade de 0,01544989 BTC, notional projetado de 1.000 USDT, risco de 200 USDT, stop-loss em 63.430,892 e take-profit em 67.961,67. Nenhuma dessas informações foi enviada para a exchange como ordem.

## Backtest e algoritmos

| Métrica | Resultado |
|---|---:|
| Estado | `ok` |
| PnL do recorte | +2,8625 |
| Retorno | +0,02862% |
| Sharpe | 0,3008 |
| Drawdown máximo | -0,06037% |
| Operações | 2 |
| Vitórias / perdas | 1 / 1 |
| Win rate | 50% |
| Profit factor | 5,9601 |
| Sinais bons | 7 |
| Sinais rejeitados | 458 |
| Dados inválidos | 0 |
| Tempo de análise e backtest | 196,87 ms |

O resultado é tecnicamente consistente com o motor, mas a amostra de duas operações é pequena e não valida rentabilidade. O profit factor elevado nesse recorte não deve ser extrapolado. A gate permaneceu conservadora, rejeitando a maioria das leituras por falta de confluência ou confiança.

O `EnsembleModel` foi carregado e respondeu, mas não há arquivos de modelos treinados no diretório `models`. Por isso, a função retornou explicitamente `hold` com confiança 0,5. Isso é um fallback neutro correto; não se deve chamar esse resultado de previsão treinada. Para ativar o ensemble real, é necessário fornecer dataset OHLCV rotulado, treinar os modelos, validar fora da amostra e versionar apenas os artefatos aprovados.

## Conclusão

O erro `-2015` está corrigido para o pacote enviado: saldo privado Demo aprovado, dados públicos aprovados e zero ordens. A estratégia atual está operacional para análise e backtest, com RiskAI bloqueando entradas sem confiança. O ensemble permanece em modo neutro por ausência de modelos treinados. O próximo estágio seguro, se desejado, é um teste separado de ordem Demo com `TRADE` habilitado e confirmação explícita, após definir quantidade mínima e critérios de cancelamento.

## Referências

[1]: https://developers.binance.com/en/docs/products/spot/demo-mode/general-info "Binance Spot Demo Mode — General Info"
[2]: https://developers.binance.com/en/docs/products/spot/rest-api "Binance Spot REST API — Request Security"

# Relatório de atualização do core — ZIA-TRADER-v17

## Resultado executivo

A engenharia do core foi sincronizada em torno de um `MarketSnapshot` único. O snapshot reúne OHLCV primário e secundário, cotação, livro de ofertas, notícias, tendências e falhas de provedores. A coleta de timeframes, mercado, livro, notícias e tendências ocorre em paralelo quando possível, reduzindo chamadas redundantes no motor principal.

A execução permanece segura por padrão: a atualização não enviou ordens, não habilitou trading live e manteve o modo simulado como default. A regra operacional implementada é: **compradores dominantes por pelo menos 2x vendedores produzem pressão de alta; vendedores dominantes por pelo menos 2x compradores produzem pressão de baixa; livro incompleto ou fluxo equilibrado produz `hold`**. Uma confirmação de pullback não concede alavancagem automaticamente.

## Alterações aplicadas

| Área | Implementação |
|---|---|
| Adaptadores e dados | `core/data_feeds.py` centraliza a coleta paralela; `MarketConnector` continua sendo a fachada única para Binance testnet/demo, simulação, Forex e demais adapters existentes. |
| Fluxo | `core/flow_analysis.py` calcula nocional comprador/vendedor, razão, imbalance, dominância e neutralidade com proteção para livro incompleto. |
| Indicadores | `core/market_signals.py` agora expõe EMA rápida/lenta, momentum, RSI, MACD, razão de volume, ATR e imbalance do fluxo. |
| Notícias e tendências | `NewsProcessor` mantém GDELT/RSS e provedores pagos opcionais; a tendência direcional usa variação de preço quando disponível, enquanto popularidade sem direção permanece neutra. CoinGecko continua como fonte de tendência de popularidade, seguindo o endpoint oficial de trending [1]. |
| Motor | `core/engine.py` usa o snapshot central, evita chamadas repetidas para timeframes e registra o contexto do fluxo nas observações shadow. |
| Aprendizado | `core/learning_layer.py` registra o resultado `after` apenas quando há candles futuros suficientes, sem look-ahead; `label_shadow_observations.py` foi alinhado a essa camada e persiste preço futuro, retorno, label e horizonte. |
| Comandos | `core/command_manager.py` expõe sincronização e análise sem ordens; a API ganhou `GET /core/analyze` e `POST /core/sync`; o console ganhou “Atualizar e validar Core”. |
| Simulação | O adapter simulado aceita `SIMULATED_ORDER_FLOW_BIAS= bullish|bearish|neutral` e `SIMULATED_ORDER_FLOW_RATIO`, com `neutral` como default. |
| Segurança operacional | `DailyStateManager` aplica estado UTC e regra 5 vitórias/2 perdas; neutro nunca autoriza entrada. |
| Diagrama | `docs/core_refinement.mmd` e `docs/core_refinement.png` foram atualizados com as camadas de comando, dados, análise, risco, execução e aprendizado. |

## Comandos de uso

O comando principal de atualização é:

```bash
python3 scripts/update_core.py
```

Ele compila `core`, `data`, `execution` e `config`, executa a suíte de regressão e regenera o PNG do diagrama. O script informa `orders_sent=0` e `live_trading_enabled=false`.

Para consultar um símbolo sem enviar ordens, use a API autenticada:

```text
GET /core/analyze?symbol=BTC/USDT
POST /core/sync
```

O corpo opcional de `/core/sync` aceita `{"symbols":["BTC/USDT"],"limit":250,"offline":false}`. Para cenário local, configure `SIMULATED_ORDER_FLOW_BIAS=neutral`, `bullish` ou `bearish`. Depois de um replay shadow, a camada de aprendizado pode rotular candles futuros com:

```bash
python3 scripts/label_shadow_observations.py dataset.csv --horizon-bars 8
```

## Validação executada

| Verificação | Resultado |
|---|---:|
| Compilação de `core`, `data`, `execution` e `config` | OK |
| Suíte de testes | **66 passed** |
| Regeneração do diagrama Mermaid | OK |
| `git diff --check` | OK |
| Ordens enviadas durante a atualização | **0** |
| Trading live habilitado durante a atualização | **Não** |
| Commit local | `d35f38c feat: integrate core market analysis and learning feeds` |

A suíte ainda emite dois avisos não bloqueantes: `python_multipart` no Starlette e a configuração `batch_first` do Transformer. Eles não falharam a validação e ficam como próximos itens de limpeza técnica.

## Próximas sugestões

Antes de qualquer ativação live, o próximo passo recomendado é validar o adapter em testnet com credenciais injetadas por secret manager, executar replay com dados reais, medir precisão por regime e testar falhas de provedor. A API de notícias deve continuar sendo tratada como contexto auxiliar, nunca como autorização isolada. GDELT é uma fonte aberta com APIs JSON em tempo real [2], e o contrato do Binance Spot Testnet deve ser conferido na documentação oficial antes de qualquer teste de execução [3].

Também é recomendável materializar o `after` diretamente ao fim de uma janela de simulação, comparar desempenho por limiar 2x1 e somente então revisar `ORDER_FLOW_RATIO_THRESHOLD`. Alterar esse limiar em produção sem walk-forward e sem controle de drawdown não é recomendado.

## Referências

[1]: https://docs.coingecko.com/reference/trending-search "CoinGecko — Trending Search List"

[2]: https://www.gdeltproject.org/data.html "GDELT Project — Data and APIs"

[3]: https://developers.binance.com/en/docs/products/spot/testnet/rest-api "Binance Developer Docs — Spot Testnet REST API"

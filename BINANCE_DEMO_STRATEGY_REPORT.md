# Validação Binance Demo — ZIA-TRADER-v17

> Validação técnica em ambiente Demo. Não é recomendação de investimento nem comprovação de rentabilidade futura. Nenhuma ordem foi enviada.

## Escopo

O arquivo `Testnet.zip` foi inspecionado sem executar conteúdo compactado. Ele continha somente um `.env`, com credenciais presentes e endpoint no host `demo-api.binance.com`. O teste foi configurado com `BINANCE_MODE=demo` e usou o adapter real publicado em `execution/binance_adapter.py`.

As chamadas realizadas foram: sincronização/validação do adapter, ticker e livro, candles Spot de 1 minuto, cálculo de sinais, backtest walk-forward e validação do RiskAI. Não foram chamados endpoints de criação, cancelamento ou alteração de ordens.

## Resultado de conectividade

| Verificação | Resultado |
|---|---|
| Host | `demo-api.binance.com` |
| Dados públicos de mercado | Aprovados |
| Candles | 500 barras de 1 minuto recebidas |
| Período observado | 2026-08-18 07:22–15:41 UTC |
| Saldo autenticado | Rejeitado com Binance `-2015` |
| Ordens enviadas | `0` |

A consulta pública funcionou, mas a chamada privada de saldo retornou `-2015 Invalid API-key, IP, or permissions for action`. Portanto, a API Demo está acessível, mas a autenticação privada da chave fornecida ainda não está homologada. A causa provável é chave criada no ambiente errado, chave revogada/expirada, permissão `USER_DATA` ausente ou restrição de IP.

## Leitura de mercado e estratégia

| Métrica | Resultado |
|---|---:|
| Último preço observado | 64.848,90 USDT |
| Bid / ask | 64.848,90 / 64.848,91 |
| Volume 24h retornado | 14.751,36526 BTC |
| Ação final | `hold` |
| Ação candidata | `hold` |
| Status | `rejected` |
| Score | -0,01952 |
| Confiança | 0,50976 |
| Volatilidade ATR | 0,0003713 |
| Regime | `lateral` |

O algoritmo **não identificou uma entrada suficientemente boa** nesse recorte. A confiança ficou abaixo do limiar operacional e os componentes não apresentaram direção convergente. O bloqueio foi correto: a estratégia retornou `hold`, e o RiskAI rejeitou a tentativa de transformar esse resultado em ordem porque a ação não era `buy` nem `sell`.

## Backtest walk-forward

| Métrica | Resultado |
|---|---:|
| Capital inicial | 10.000,00 |
| Capital final | 9.999,6022 |
| PnL total | -0,3978 |
| Retorno | -0,00398% |
| Sharpe | -0,04463 |
| Drawdown máximo | -0,08453% |
| Operações encerradas | 2 |
| Operações vencedoras | 1 |
| Operações perdedoras | 1 |
| Win rate | 50% |
| Profit factor | 0,8662 |
| Sinais bons | 7 |
| Sinais rejeitados | 458 |
| Dados inválidos | 0 |

O resultado desse recorte é **neutro a levemente negativo**, não uma evidência de assertividade ou lucro. A amostra de duas operações é pequena demais para avaliar a estratégia. O número alto de sinais rejeitados mostra que a gate de confluência está conservadora; isso reduz operações, mas não prova que os limiares sejam ótimos.

## RiskAI

O RiskAI bloqueou corretamente o sinal efetivo porque a ação foi `hold`. Um segundo caso hipotético, apenas de sizing e sem execução, produziu quantidade de 0,01542046 BTC, notional projetado de 1.000 USDT, risco por operação de 200 USDT, stop-loss em 63.551,922 e take-profit em 68.091,345. Esse caso foi um cálculo de validação sobre saldo fictício do backtest, não uma ordem Demo e não uma recomendação de tamanho.

## Conclusão

A leitura pública Demo, o pipeline de candles, os sinais, o backtest e os bloqueios de risco funcionaram. A autenticação privada permanece pendente e impede validar saldo, reconciliação de conta e execução de ordens Demo. Antes de qualquer teste de ordem, é necessário criar ou confirmar a chave dentro do Binance Demo Mode, habilitar `USER_DATA`, verificar a whitelist de IP do servidor e repetir a leitura de saldo. `TRADE` só deve ser habilitado para um teste explícito, previamente confirmado.

## Referências

[1]: https://developers.binance.com/en/docs/products/spot/demo-mode/general-info "Binance Spot Demo Mode — General Info"
[2]: https://developers.binance.com/en/docs/products/spot/testnet/rest-api "Binance Spot Testnet — REST API"

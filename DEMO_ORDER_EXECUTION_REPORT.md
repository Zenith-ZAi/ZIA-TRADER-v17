# Relatório de execução de ordem Binance Demo

**Data da execução:** 2026-08-18 18:23:18 UTC  
**Ambiente:** `demo-api.binance.com`  
**Credenciais:** carregadas exclusivamente de variáveis de ambiente; nenhum segredo foi versionado.

## Payload autorizado

| Campo | Valor |
|---|---:|
| Símbolo | `BTCUSDT` (`BTC/USDT`) |
| Lado | `BUY` |
| Tipo | `MARKET` |
| Quantidade solicitada | `0.00015 BTC` |
| Preço estimado no dry-run | `64.734,35 USDT/BTC` |
| Valor estimado no dry-run | `9,7101525 USDT` |

A confirmação explícita do usuário foi recebida antes do envio. Foi enviada somente uma ordem, sem ordem adicional e sem cancelamento posterior, pois uma ordem `MARKET` foi preenchida imediatamente.

## Resultado da Binance Demo

| Campo | Resultado |
|---|---:|
| `order_id` | `57614421337` |
| Status do adapter | `success` |
| Status da exchange | `FILLED` |
| Quantidade executada | `0.00015 BTC` |
| Preço médio preenchido | `64.788,64 USDT/BTC` |
| Valor acumulado executado | `9,71829600 USDT` |
| Comissão reportada | `0` |

A consulta de status posterior confirmou novamente `FILLED` para a ordem `57614421337`.

## Saldo observado

| Ativo | Antes | Depois |
|---|---:|---:|
| `USDT` | `5000.000000` | `4990.281704` |
| `USDC` | `5000.000000` | `5000.000000` |
| `BTC` | não presente no saldo positivo | `0.00014985` |

O valor executado foi aproximadamente **9,718296 USDT**, com pequena diferença em relação à estimativa devido à execução de mercado. A estratégia estava em `HOLD` no dry-run, com candidato `BUY` e confiança `0.5757`, abaixo do limiar operacional `0.70`; portanto, esta execução foi um **smoke test manual autorizado**, não uma validação de que a IA deveria ter aberto posição automaticamente.

Nenhum token, chave privada, arquivo `.env` ou segredo foi incluído neste relatório.

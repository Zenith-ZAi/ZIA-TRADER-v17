# Relatório de execução — Protocolo Sandbox com API pública Binance

**Data da coleta:** 18 de agosto de 2026, UTC  
**Ativo:** BTCUSDT  
**Intervalo:** 1 hora  
**Fonte:** endpoint público de klines da Binance, sem autenticação e sem acesso a endpoints de ordem [1] [2].  
**Código:** `scripts/fetch_binance_ohlcv.py` e `scripts/run_binance_protocol.py`.

> **Aviso financeiro:** este documento é uma validação técnica de software e não garante retorno, assertividade futura ou adequação a uma decisão de investimento. A operação de trading continua sujeita à perda de capital.

## 1. Coleta e integridade

O coletor foi executado com paginação de até 1.000 candles por chamada, retirando a vela ainda aberta, ordenando timestamps e removendo duplicatas somente por `open_time`. O período solicitado foi de 1º de janeiro de 2020 a 31 de dezembro de 2024, para incluir 2020 e 2021 conforme o protocolo anexado.

| Verificação | Resultado |
|---|---:|
| Candles recebidos | `43.816` |
| Primeiro candle | `2020-01-01T00:00:00Z` |
| Último candle | `2024-12-31T23:00:00Z` |
| Duplicatas | `0` |
| Valores ausentes | `0` |
| OHLCV consistente | `true` |
| Maior variação absoluta de abertura contra fechamento anterior | `0,189739%` |
| SHA-256 do CSV | `a7b9bfd6c567938eafccfcf9e15062b80b5653f327e33b31a7a614be92223aa4` |

O CSV bruto permanece local e ignorado pelo Git; o hash permite repetir a auditoria sobre exatamente o mesmo arquivo. A fonte pública forneceu klines, não um replay tick-a-tick.

## 2. Backtest completo com softskill e fricção

O backtest foi walk-forward, sem usar valores posteriores ao candle avaliado. A softskill utilizou EMA 200, pivôs confirmados, RSI, exaustão por volume, rompimento com volume e níveis ATR. A fricção foi ativada com comissão de `0,05%`, slippage determinístico de `0,5–2,0` ticks, seed `42` e latência sorteada no intervalo `150–500 ms`, sem `sleep` para não distorcer o tempo de processamento.

| Métrica | Resultado |
|---|---:|
| Capital inicial | `10.000,00` |
| PnL líquido | `95,2362069444` |
| Retorno | `0,952362%` |
| Sharpe | `0,092807` |
| Drawdown máximo | `-0,337662%` |
| Operações | `8` |
| Win rate | `87,5%` |
| Profit factor | `96,093691` |
| Custos registrados | `8,0158938427` |
| Barras em janela de evento | `10` |
| Candidatos bloqueados por evento | `2` |

O resultado é positivo, mas **não passa no critério de Sharpe maior que 1,0**. O profit factor elevado deve ser desconsiderado como evidência forte porque deriva de somente oito operações. A softskill não deve ser liberada para trading real com base neste recorte.

## 3. Comparação controlada

Foi executado o mesmo período, com a mesma fricção e o mesmo calendário, comparando o filtro pullback contra o sinal determinístico sem pullback.

| Métrica | Pullback ativo | Pullback desativado |
|---|---:|---:|
| PnL líquido | `95,2362` | `87.532,1353` |
| Retorno | `0,9524%` | `875,3214%` |
| Sharpe | `0,0928` | `1,1453` |
| Drawdown máximo | `-0,3377%` | `-1,9176%` |
| Operações | `8` | `1.598` |
| Win rate | `87,5%` | `57,1339%` |
| Profit factor | `96,0937` | `2,8476` |
| Custos | `8,0159` | `6.385,7600` |

A comparação não é prova de superioridade do baseline. O backtest atual permite vendas sem uma regra explícita de inventário/borrow para short, e o resultado sem pullback apresenta capitalização muito agressiva. Antes de qualquer conclusão econômica, é necessário implementar restrição de inventário ou modelo de margem, slippage por spread real e reconciliação de posição.

## 4. Regimes de mercado

As sessões foram definidas diretamente a partir dos quantis de volatilidade rolling de 24 horas do próprio OHLCV. Isso é um particionamento analítico, não uma classificação econômica perfeita de regimes.

| Sessão | PnL | Sharpe | Drawdown | Trades | Win rate | Resultado |
|---|---:|---:|---:|---:|---:|---|
| Range / baixa volatilidade | `6,8672` | `0,07294` | `-0,07350%` | `2` | `50,0%` | Não demonstra vantagem |
| Turbulenta / alta volatilidade | `-9,6339` | `-0,03266` | `-0,21913%` | `3` | `33,3333%` | Reprovada em PnL e Sharpe |

A softskill apresentou pior comportamento na sessão turbulenta. O limite de drawdown de 15% foi respeitado, mas isso não compensa PnL negativo nem Sharpe inferior a 1,0.

## 5. Gaps de 2%

Foram injetados cinco gaps sintéticos de 2% imediatamente após cinco entradas observadas no backtest completo. As injeções são um teste de estresse, não dados históricos observados.

| Métrica | Resultado |
|---|---:|
| Gaps injetados | `5` |
| PnL líquido | `58,0756485013` |
| Sharpe | `0,054503` |
| Drawdown máximo | `-0,337662%` |
| Operações | `8` |
| Win rate | `62,5%` |
| Profit factor | `3,661778` |
| Drawdown abaixo de 15% | `true` |

O critério de drawdown foi respeitado, mas o Sharpe continuou baixo. Portanto, o teste de gaps não autoriza concluir que o algoritmo está imune a gaps; apenas confirma que o recorte sintético não ultrapassou o teto de drawdown configurado.

## 6. Liquidez falsa / spoofing de volume

Cinco cenários foram derivados de candidatos reais do OHLCV e receberam volume quatro vezes maior, fechamento contrário ao sinal e ausência de confirmação de momentum. O resultado foi:

| Cenários | Filtrados como HOLD | Critério |
|---:|---:|---|
| `5` | `5` | **Aprovado neste teste** |

Esse resultado valida apenas os cinco cenários sintéticos construídos pelo executor. Não é uma prova de proteção contra spoofing real no livro de ordens, porque o endpoint utilizado não forneceu fluxo tick-a-tick ou histórico completo de ordens.

## 7. Calendário econômico

Foram criados dez eventos sintéticos, distribuídos no intervalo histórico, com janela de bloqueio de 60 segundos antes e 300 segundos depois. O motor identificou dez barras dentro das janelas e bloqueou dois candidatos determinísticos. Nenhum desses eventos é um release econômico real; o teste valida o mecanismo temporal e não a qualidade de um calendário macro.

## 8. Tick-a-tick e banco

O critério do anexo que exige 2,3 milhões de ticks, processamento inferior a 200 ms por tick e ausência de colisões **não foi executado**. A API pública aplicada nesta tarefa fornece klines agregados. Não seria correto transformar 43.816 candles em 2,3 milhões de ticks ou declarar latência tick-a-tick sem um feed de replay real.

## 9. Veredito

| Critério do protocolo | Status |
|---|---|
| Coleta pública e integridade OHLCV | **Aprovado** |
| Fricção com custos contabilizados | **Aprovado tecnicamente** |
| PnL líquido positivo no recorte completo | **Aprovado no recorte** |
| Drawdown abaixo de 15% no recorte e gap sintético | **Aprovado no recorte** |
| Cinco cenários sintéticos de volume falso filtrados | **Aprovado no teste** |
| Dez janelas sintéticas de calendário | **Executado; 2 candidatos bloqueados** |
| Sharpe líquido acima de 1,0 | **Reprovado: 0,092807** |
| Regime turbulento positivo | **Reprovado: PnL -9,6339** |
| Replay de 2,3 milhões de ticks | **Não testado** |

**Conclusão:** a aplicação da API pública funcionou e o protocolo OHLCV foi executado com dados reais da Binance. O sistema deve permanecer em pesquisa/shadow mode. O próximo ajuste prioritário é melhorar a frequência e a robustez do pullback sem relaxar simultaneamente todos os filtros: calibrar pivôs, volume, RSI e ATR em validação temporal separada, além de corrigir as premissas de short, proteção de posição e custos por spread real.

## Referências

[1]: https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=1000 "Binance Spot public klines endpoint"
[2]: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints "Binance Spot API — public market-data endpoints"
[3]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/core/backtest_engine.py "ZIA walk-forward backtest engine"
[4]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/docs/AI_SOFTSKILL_PULLBACK.md "ZIA pullback softskill policy"

> **Basis:** PnL e Sharpe vêm do `BacktestEngine` com comissão de 0,05%, slippage configurável e stop/alvo ATR quando o pullback está ativo. **Time:** candles fechados UTC de 2020-01-01 a 2024-12-31, coletados em 2026-08-18. **Assumptions:** eventos e gaps são sintéticos; a comparação sem pullback permite short sem modelo de borrow. **Sources & Confidence:** OHLCV veio do endpoint público Binance; confiança estatística é baixa para a estratégia pullback por haver oito operações. **Compliance:** This is research and analysis only, not personalized financial advice.

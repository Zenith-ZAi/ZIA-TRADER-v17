# Validação e refinamento de performance — Binance Demo

> Teste técnico em ambiente Demo. Nenhuma ordem foi criada, cancelada ou alterada. Os valores de mercado são apenas o recorte observado durante a execução e não representam recomendação de investimento.

## Configuração recebida

O novo `(1).env` não utilizava `BINANCE_BASE_URL` diretamente. Ele fornecia `BINANCE_BASE_URL_DEMO`, `BINANCE_BASE_URL_TESTNET` e `BINANCE_BASE_URL_WebSocket`, além de `BINANCE_API_KEY` e `BINANCE_SECRET_KEY`. Os valores sensíveis foram apenas detectados como presentes e nunca foram impressos.

O sistema foi refinado para selecionar automaticamente a URL Demo quando `BINANCE_MODE=demo`, mantendo `BINANCE_BASE_URL` como override explícito. O Compose também passou a encaminhar as duas URLs separadas sem transformar uma variável Demo vazia em uma URL Testnet por acidente.

## Validação da API Demo

| Check | Resultado após refinamento |
|---|---:|
| Ambiente | `demo` |
| Host | `demo-api.binance.com` |
| Ordens enviadas | `0` |
| Sincronização de relógio | Aprovada; aproximadamente 2.979 ms |
| Ticker + bookTicker | Aprovado; aproximadamente 2.680 ms |
| 500 candles de 1 minuto | Aprovado; aproximadamente 2.957 ms |
| Saldo privado | Falhou com `-2015` em aproximadamente 588 ms |

Os endpoints públicos continuaram funcionando. A consulta privada de saldo continuou retornando `BinanceAuthenticationError -2015`, portanto a nova configuração ainda precisa de uma chave criada no Demo Mode com permissão `USER_DATA` e, se aplicável, IP autorizado. O refinamento de código não mascara esse erro.

## Refinamento de análise e backtest

O backtest anterior recalculava EMA, MACD, RSI, ATR, retornos e volume para cada janela walk-forward. Isso gerava custo aproximadamente quadrático. Foi adicionado `MarketSignalCache`, que pré-calcula séries causais uma vez e consulta cada posição sem usar candles futuros. O backtest passou a consumir o cache sem mudar a regra de `hold`, confluência, volatilidade ou risco.

| Benchmark com 500 candles Demo | Antes | Depois |
|---|---:|---:|
| Sinal único | 5,82 ms médios | 5,39 ms médios |
| Backtest completo | 2.246,76 ms médios | 187,39 ms médios |
| Redução observada | — | **91,65%** |

O benchmark otimizado continuou classificando o sinal atual como `hold`/`rejected`, com 7 sinais bons, 458 rejeitados e nenhum dado inválido. A decisão de não operar permaneceu preservada. O PnL de cada execução não deve ser comparado entre chamadas distintas da Demo, porque o recorte de candles pode mudar; no último recorte, o backtest teve duas operações e não fornece amostra suficiente para inferir rentabilidade.

## Testes locais

A compilação e a suíte existente terminaram com **19 testes aprovados**. O carregamento preguiçoso de `exchangeInfo` permanece desativado por padrão para reduzir o custo de startup; os filtros são carregados sob demanda por símbolo antes de normalizar uma ordem. Use `BINANCE_PRELOAD_EXCHANGE_INFO=true` somente se o processo realmente precisar pré-carregar todos os símbolos.

## Próximo bloqueio

A próxima ação operacional é recriar ou confirmar a chave diretamente no Binance Demo, verificar `USER_DATA`, revisar a whitelist de IP e reiniciar o processo com os aliases corretos. O teste de saldo deve passar antes de qualquer tentativa de criação ou cancelamento de ordem. `TRADE` deve permanecer desabilitado até haver confirmação explícita para uma ordem de teste.

## Referências

[1]: https://developers.binance.com/en/docs/products/spot/demo-mode/general-info "Binance Spot Demo Mode — General Info"
[2]: https://developers.binance.com/en/docs/products/spot/rest-api "Binance Spot REST API — Request Security"

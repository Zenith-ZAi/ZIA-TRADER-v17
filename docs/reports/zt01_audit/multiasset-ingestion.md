# Auditoria read-only — ingestão multiativo

**Assunto único:** dados BTC, dólar, euro, cripto e ações
**Checkout auditado:** `/home/ubuntu/ZIA-TRADER-v17-phase9-resume`
**Head verificado:** `09ea8c8` (`fix: secure backend provider credentials and sandbox data smoke`)
**Data da auditoria:** 2026-11-19
**Escopo:** collector unificado, endpoints de símbolos/timeframes/classes de ativo, qualidade/proveniência e integração com análise. Não houve edição de código, Git, menus ou flags; não houve browser nem credencial real.

## Veredito

O backend tem um caminho read-only verificável para **BTC/USDT em OHLCV da Binance pública**, com normalização, rejeição de candle em formação, persistência idempotente e leitura determinística de features/sinal no smoke já consolidado. Isso não equivale a uma cobertura multiativo integrada.

O `UnifiedMarketDataCollector` grava candles no `market_candles`, mas o caminho de análise (`MultiTimeframeFeed`/`RoboTraderUnified`/`CoreCommandManager`) continua consultando o `MarketConnector` diretamente. A coleta declara explicitamente `trading_feed_updated=false`; portanto, um candle persistido pelo collector não passa automaticamente a alimentar `/core/analyze`, `/core/sync` ou o motor.

A cobertura real disponível no código é assimétrica:

| Alvo do piloto | Identidade do collector | Fonte/capacidade implementada | Timeframe no collector/API | Gate e credencial | Semântica permitida |
|---|---|---|---|---|---|
| `BTC/USDT` | `crypto`, `BTC/USDT` | `binance_public`, `GET /api/v3/klines` em `data-api.binance.vision` | `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d` | `MARKET_DATA_INGESTION_ENABLED` + `MARKET_DATA_BINANCE_PUBLIC_ENABLED`; sem chave | OHLCV de um **par de exchange**, com quote `USDT`; não é Forex nem dado executável por si só |
| `EUR/USD` | `forex`, `EUR/USD` | `alpha_vantage`, função `FX_DAILY` | somente `1d` | gate global + `MARKET_DATA_ALPHA_VANTAGE_ENABLED` + `ALPHA_VANTAGE_API_KEY`; entitlement/licença ainda não homologados | referência diária; não substitui cotação, spread, profundidade ou feed executável intraday |
| `AAPL` | `equity`, `AAPL` | `alpha_vantage`, função `TIME_SERIES_DAILY` | somente `1d` | gate global + gate Alpha Vantage + chave; entitlement/licença ainda não homologados | referência diária de ação; não é cotação executável intraday e não traz venue/moeda no identificador |

`yahoo_chart` permanece bloqueado no collector por autorização/termos pendentes. `coingecko` é contexto agregado de mercado/tendência e permanece bloqueado como fonte de candles; não foi promovido a OHLCV oficial. Os defaults de ingestão são desligados. O catálogo administrativo só informa seleção/gates/presença de credencial, não saúde, entitlement ou autorização de ordens.

A verificação local executou `33 passed, 1 warning` em `tests/test_market_data_collector.py`, `tests/test_feed_quality.py`, `tests/test_provider_catalog.py` e `tests/test_application_factory.py`. A checagem determinística adicional não acessou rede: confirmou `BTCUSDT -> BTC/USDT`, `eur/usd -> EUR/USD`, `AAPL -> AAPL`; gate global fechado retorna `ingestion_disabled`; Alpha Vantage habilitado sem chave retorna `blocked/missing_credentials`; e a normalização do adapter crypto transforma `EUR/USD` em `EURUSD`, evidência da limitação de roteamento abaixo.

## Achados materiais

### 1. O collector unificado não está conectado ao feed usado pela análise

**Evidência:** `core/command_manager.py:106-112` documenta a coleta como “outside the trading feed”; `api/routers/market.py:123-142` expõe a rota como coleta que nunca atualiza o feed; `core/engine.py:224-232` constrói o snapshot através de `self.data_feed`; `core/data_feeds.py:64-68` recebe um `market_connector`, não o `UnifiedMarketDataCollector` nem um leitor de `market_candles`. A resposta do collector mantém `trading_feed_updated=False` e `model_weights_changed=False` (`core/market_data_collector.py:276-290`).

**Impacto:** persistir um candle de `binance_public`, `alpha_vantage` ou mock não faz esse dado aparecer na análise. O smoke comprova ingestão → SQLite → features → sinal somente para seu caminho específico de teste; não comprova collector → snapshot do core. Sem uma ponte aprovada, não se deve anunciar que EUR/USD ou AAPL coletados estão integrados à análise.

**Aceite binário proposto:** para cada alvo do piloto, ou (a) um adaptador read-only explicitamente aprovado lê as linhas persistidas e entrega ao `MultiTimeframeFeed` preservando `source`, `asset_class`, `symbol` e `timeframe`, com o hash das linhas usado na análise, ou (b) a chamada que tentar usar somente candles persistidos falha fechada com código explícito de feed não conectado. Nenhuma das duas condições deve gerar ordem ou alterar pesos.

### 2. A matriz de providers, classes e timeframes não oferece cobertura intraday para Forex/ações

**Evidência:** `core/market_data_collector.py:16-18` declara três classes e sete timeframes; `api/routers/market.py:19-29` restringe a rota aos mesmos sete timeframes; `_collect_one` aceita Binance somente para `crypto` e Alpha Vantage somente para `equity`/`forex` em `1d` (`core/market_data_collector.py:314-319`). A implementação Alpha usa `TIME_SERIES_DAILY` para equity e `FX_DAILY` para Forex (`core/market_data_collector.py:385-435`). O `asset_class` é único por request, não misto.

**Impacto e distinção semântica:** `BTC/USDT` é um par de exchange com quote em `USDT`; não é equivalente a `EUR/USD`, que é um par Forex, nem a `AAPL`, que é uma ação. Uma barra diária de Alpha Vantage é dado de referência e não comprova preço executável, bid/ask, spread, profundidade, latência ou custos intraday. O fato de o adapter Binance ou o validador geral conhecerem outros timeframes não cria uma fonte Alpha intraday.

**Aceite binário proposto:** mocks devem produzir `completed/persisted` para `BTC/USDT` em `1h`, `partial/attention` ou `blocked` sem chamada externa para providers desabilitados, e `persisted` para `EUR/USD`/`AAPL` apenas em `1d`. Pedidos `5m`/`1h` para Alpha Vantage devem retornar `unsupported_timeframe` antes de uma chamada. Cada linha persistida deve conservar a chave composta `(source, asset_class, symbol, timeframe, timestamp)` e o status de volume (`reported` para AAPL; `unavailable_zero` para FX quando a fonte não fornece volume). Nenhum resultado deve ser rotulado como feed oficial/executável sem aprovação de entitlement, licença e contrato de mercado.

### 3. Há um único adapter global por processo; o runtime não roteia BTC, Forex e ação por classe

**Evidência:** `execution/market_connector.py:405-423` escolhe um único adapter a partir de `MARKET_ADAPTER`, `MARKET_TYPE` e `FOREX_MODE`; `api/routers/market.py:72-84` e `/core/analyze` (`:87-99`) recebem apenas `symbol`, sem `asset_class` ou venue; `RoboTraderUnified` usa uma única instância e percorre `settings.SYMBOLS` (`core/engine.py:55`, `:221-232`). A função `normalize_symbol` trata crypto removendo separadores, Forex mantendo par e B3 acrescentando `.SA` (`execution/market_connector.py:29-43`).

**Impacto:** no adapter crypto, `EUR/USD` vira `EURUSD` e `AAPL` não recebe uma identidade de venue; no adapter B3, `AAPL` vira `AAPL.SA`; no adapter Forex, BTC não é um símbolo válido. Assim, uma lista mista no mesmo runtime pode produzir normalização silenciosa ou falha no provider errado. O endpoint de coleta aceita uma classe por request, mas isso não resolve o roteamento do caminho de análise.

**Aceite binário proposto:** um request misto `[BTC/USDT, EUR/USD, AAPL]` deve ou rotear cada símbolo para um connector cuja classe/venue/moeda estejam declaradas, ou rejeitar com `mixed_asset_class_not_supported`; nunca deve transformar silenciosamente `EUR/USD` em `EURUSD` dentro de adapter crypto. O snapshot de cada alvo deve expor identidade canônica incluindo ao menos `asset_class`, venue/fonte e moeda de quote. `BTC/USDT`, `EUR/USD` e `AAPL` precisam ser três casos separados no piloto, não três símbolos enviados a um adapter global.

### 4. Qualidade de OHLCV, proveniência e executabilidade são contratos diferentes e hoje chegam por caminhos diferentes

**Evidência:** o collector rejeita candle futuro/em formação, valida OHLC e conserva `source`/`volume_status` (`core/market_data_collector.py:351-383`, `:439-475`); o `MultiTimeframeFeed` remove a última barra aberta e valida gaps, staleness e timestamps (`core/data_feeds.py:143-214`, `:216-256`). Porém, o histórico entregue pelo adapter é um `DataFrame` sem a proveniência do collector, enquanto a proveniência explícita é exigida principalmente para a cotação corrente. O `ForexPublicReadOnlyAdapter` usa `forex-python` com `timestamp_source="unverified"` e timestamp nulo quando esse caminho funciona (`execution/market_connector.py:206-238`); o validador do feed só aceita `exchange_tick`, `ohlcv_candle` ou `simulated` (`core/data_feeds.py:176-204`), então esse caso deve falhar fechado. O fallback Yahoo pode fornecer `ohlcv_candle`, mas continua sendo Yahoo read-only não homologado como feed oficial.

**Impacto:** passar a validação de OHLCV não torna uma série executável. O collector não coleta livro, bid/ask, spread, profundidade, slippage ou custos; a análise busca esses dados separadamente. Para EUR/USD e AAPL, o caminho diário pode ser útil para pesquisa/shadow, mas não deve autorizar entrada intraday; para BTC, uma cotação pública sem livro atualizado também não substitui os gates de microestrutura.

**Aceite binário proposto:** mocks devem verificar que timestamp futuro, candle aberto, série stale, gap inválido e cotação sem timestamp/proveniência são rejeitados; o snapshot deve devolver a fonte e o papel (`exchange_ohlcv`, `daily_reference`, `simulated_context`) de forma explícita. Sem quote/bid/ask/order book executáveis, `entry_allowed` deve ser `false`, `execution_authorized` deve ser `false` e `orders_sent` deve ser `0`. Dados diários de FX/ações devem permanecer marcados como referência/shadow, nunca como feed intraday.

### 5. Falta evidência de um piloto de três ativos e de uma integração de análise class-aware

**Evidência:** os testes do collector exercitam canonicalização, Binance pública simulada, idempotência, bloqueio de Yahoo/CoinGecko e gates; os testes de feed exercitam qualidade genérica e BTC/Forex simulados. Não há, no conjunto auditado, um teste de mock Alpha Vantage que cubra simultaneamente `FX_DAILY` para `EUR/USD` e `TIME_SERIES_DAILY` para `AAPL`, nem um cenário único que preserve a identidade dos três alvos até a análise. O smoke real consolidado é limitado a BTC/USDT 1h, sem chave, sem ordem e sem provar a ponte descrita no Achado 1.

**Impacto:** os contratos individuais estão razoavelmente protegidos, mas a afirmação “cobertura multiativo” ainda não tem evidência reprodutível. O próximo incremento deve ser de cobertura e contrato read-only, não de liberação de trading.

**Aceite binário proposto para o piloto:**

1. Em SQLite temporário vazio, mocks de Binance/Alpha Vantage gravam séries fechadas para `BTC/USDT`/`1h`, `EUR/USD`/`1d` e `AAPL`/`1d`; a reimportação mantém a contagem e atualiza somente a mesma chave composta. Resultado: `orders_sent=0`, sem intenção de ordem e sem credencial real.
2. O teste opcional Binance público usa somente `https://data-api.binance.vision` e `GET /api/v3/klines`, sem header de chave, saldo, endpoint privado ou ordem. Se a fonte estiver indisponível, o resultado é `attention`/falha explícita, nunca dados fabricados.
3. Cada série possui pelo menos 35 candles fechados e passa validação de OHLCV, timestamp, gap e staleness; o sinal determinístico retorna objeto de análise ou `HOLD/bad_data`, sem autorização de execução.
4. `EUR/USD` e `AAPL` passam somente pela matriz diária mockada; pedidos intraday são bloqueados. A saída registra `source`, `asset_class`, `symbol`, `timeframe`, papel da fonte e status de volume.
5. A análise é executada separadamente por classe através de adapter/mock class-aware. O teste comprova que candles persistidos pelo collector só entram no core por uma ponte explícita aprovada; sem essa ponte, a chamada falha fechada.
6. Um caso misto confirma rejeição ou roteamento explícito de classes; nenhuma normalização crypto pode converter `EUR/USD` em `EURUSD` sem que o contrato declare a mudança de instrumento.

## Incremento recomendado

Abrir um incremento posterior e isolado de **contrato read-only multiativo**, sem alterar flags de execução: (1) definir uma especificação por ativo com `asset_class`, venue, quote currency, provider, papel da fonte, timeframe e grau de execução; (2) implementar ou recusar explicitamente a ponte entre `market_candles` e `MultiTimeframeFeed`; (3) criar os mocks dos três alvos e o piloto opcional Binance público; (4) manter Alpha Vantage diário como referência até confirmar chave, quota, entitlement e licença; (5) manter Yahoo e CoinGecko fora do papel de feed oficial. O incremento deve preservar `live/autonomia/manual/autostart` desligados e não deve introduzir ordens, Testnet ou credenciais reais.

## Bloqueadores atuais

- Não existe fonte oficial/executável intraday habilitada no collector para `EUR/USD` ou `AAPL`; Alpha Vantage é diário, exige chave/gate e ainda não está homologado quanto a entitlement/licença.
- O collector persistido não alimenta diretamente o feed usado por `/core/analyze`, `/core/sync` ou pelo engine.
- O runtime possui um `MarketConnector` global sem roteamento por classe/venue; uma lista mista pode ser normalizada para o adapter errado.
- O piloto multiativo com mocks e critérios de proveniência ainda não está presente; a evidência real consolidada permanece limitada a BTC/USDT público, sem ordens.

## Conclusão

O incremento atual pode ser aceito como base segura de ingestão read-only e gates de provedores, não como cobertura multiativo operacional. A próxima aceitação deve ser binária: cada um dos três alvos tem contrato, fonte e semântica explicitamente corretos, ou permanece em `HOLD`/bloqueado. Em particular, não se deve tratar quote de exchange em `USDT`, par Forex `EUR/USD` e ação `AAPL` como o mesmo instrumento, nem converter dado diário em feed intraday executável.

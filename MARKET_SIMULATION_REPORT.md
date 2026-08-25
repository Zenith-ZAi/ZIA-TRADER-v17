# Relatório de simulação e validação de APIs — ZIA-TRADER-v17

## Escopo e segurança

Esta validação foi executada somente em **public read-only**, **shadow** e **paper**. Nenhuma ordem foi enviada, nenhuma credencial do anexo foi carregada e o modo de trading live permaneceu desabilitado. As chaves que apareceram no arquivo enviado devem ser revogadas e substituídas nos respectivos provedores; o arquivo não foi copiado para o repositório.

## Dados públicos coletados

| Fonte | Resultado | Evidência sanitizada |
|---|---|---|
| Binance public market data | OK | 499 candles BTCUSDT de 1h, sem duplicatas, intervalo de 2026-08-04 20:00 UTC a 2026-08-25 14:00 UTC; o coletor agora usa `https://data-api.binance.vision/api/v3/klines`. |
| Yahoo global | OK | 32 candles de AAPL em 1h, sem duplicatas. |
| Yahoo B3 read-only | OK | 80 candles de PETR4 em 1d, sem duplicatas; adapter marcado como somente leitura. |
| Forex público | OK | 80 candles de EUR/USD em 1d, sem duplicatas; adapter marcado como somente leitura. |

O coletor Binance passou a preservar `quote_asset_volume`, `taker_buy_base_volume` e `taker_buy_quote_volume`. Assim, o replay calcula uma aproximação observável do nocional comprador e vendedor por candle, sem fabricar fluxo.

## Replay com aprendizado before/after

O comando `scripts/run_learning_replay.py` foi executado com BTCUSDT, intervalo de 1h, 499 candles e horizonte futuro de 8 candles. Foram criadas 456 observações históricas, sempre calculando o contexto **before** até a barra corrente e rotulando o **after** somente quando as oito barras futuras existiam.

| Métrica | Resultado |
|---|---:|
| Observações criadas | 456 |
| Observações rotuladas | 456 |
| Observações neutras/hold | 455 |
| Observações direcionais | 1 |
| Fluxo neutro | 429 |
| Fluxo bearish | 12 |
| Fluxo bullish | 15 |
| Sinais buy confirmados | 1 |
| Sinais sell confirmados | 0 |
| Ordens enviadas | **0** |
| Trading live | **Não** |

O resultado não deve ser lido como recomendação ou como estimativa de retorno futuro. Ele mostra que, com a exigência de confirmação 2x1 e os demais gates atuais, a amostra produziu poucos sinais direcionais. O único sinal buy não teve resultado positivo no horizonte definido; isso é uma observação de uma amostra curta, não uma conclusão estatística sobre a estratégia.

O replay anterior do motor live criou apenas observações na barra mais recente. Por isso, ao executar o rotulador sobre ele, as sete observações foram corretamente adiadas: não havia candles futuros suficientes. A camada nova corrige isso no replay histórico e mantém a regra contra look-ahead.

## Teste de APIs de notícias

O comando `scripts/ingest_news.py` foi executado com BTC/USDT e ETH/USDT, sem chaves. O resultado foi:

| Provedor | Resultado | Tratamento |
|---|---|---|
| Google News RSS | OK | 20 artigos normalizados e persistidos/atualizados no banco local de teste. |
| CoinGecko trending | OK | 1 tendência persistida/atualizada; popularidade foi mantida separada de direção. |
| GDELT DOC | Timeout no Sandbox | O timeout configurado foi respeitado; o provider foi marcado como indisponível e o fluxo continuou com fallback. Uma sondagem independente de 20 segundos também expirou. |
| Provedores pagos/opcionais | Não chamados | Sem chaves válidas no ambiente seguro de teste. |

O score de tendência no ingest foi corrigido para usar somente `price_change_24h` quando disponível. Ranking de popularidade, sozinho, não é tratado como alta ou baixa. O código mantém cache, timeout e status por provedor.

## Limitações do Sandbox

O Sandbox é apropriado para esta execução pontual, testes, replay e geração de artefatos, mas não deve ser tratado como um servidor de mercado 24/7. Ele pode hibernar quando fica inativo, não oferece garantia de processo persistente, pode perder serviços ou processos ao fim da sessão e não é um destino adequado para receber callbacks, webhooks ou manter polling minuto a minuto. Dependências instaladas também não devem ser presumidas como permanentes entre sessões novas.

A rede de saída pode apresentar timeout, bloqueio, variação de latência ou restrições específicas do ambiente. Nesta execução, GDELT expirou enquanto RSS, CoinGecko, Binance público e Yahoo responderam. Isso não prova indisponibilidade global do GDELT; apenas registra que ele não respondeu dentro do limite observado a partir do Sandbox. O sistema mantém fallback e fail-closed para entradas quando o contexto mínimo de notícias não está saudável.

Para operação contínua, o processo deve ser hospedado em ambiente persistente apropriado, com monitoramento, armazenamento durável, rotação de credenciais e controle de rate limits. O Sandbox atual não deve ser usado como substituto de uma infraestrutura de produção.

## Limitações do Binance Demo/Testnet

O Demo/Testnet é um ambiente virtual de teste, separado do saldo real. A documentação da Binance informa que o Demo pode apresentar diferenças em dados de gráfico, preço do livro e execução quando comparado ao ambiente live [1]. O Demo também tem disponibilidade condicionada à região/eligibilidade e não suporta algumas funções, incluindo bots no Spot Demo e determinados recursos de Futures [1].

O Spot Testnet possui limites de IP, ordens, filtros de exchange e filtros de símbolo semelhantes aos da API Spot [2]. Isso significa que o teste precisa validar `minQty`, `stepSize`, `tickSize`, notional mínimo, relógio, assinatura e tratamento de status desconhecido. O código existente mantém o adapter real limitado aos hosts HTTPS conhecidos de Testnet/Demo e bloqueia a escrita quando as flags de autonomia/shadow não autorizam.

Para market data público, a documentação geral da Binance recomenda o domínio `data-api.binance.vision` [3]. O coletor foi atualizado para esse domínio e não usa API key. Endpoints privados, assinados e de ordem não foram chamados nesta validação. A Binance também informa que limites são aplicados por IP, que respostas 429 exigem backoff e que violações repetidas podem resultar em bloqueio temporário [3].

## Implementações salvas

| Arquivo | Função |
|---|---|
| `scripts/run_learning_replay.py` | Replay causal com fluxo público e aprendizado before/after. |
| `scripts/test_free_market_data.py` | Teste read-only de Binance, Yahoo global, B3 e Forex. |
| `scripts/fetch_binance_ohlcv.py` | Coleta pública com métricas de volume comprador/vendedor e URL configurável. |
| `core/learning_layer.py` | Rotulagem futura sem look-ahead; `hold` não é contado como perda direcional. |
| `.env.example` | Configuração da URL pública e dos parâmetros do replay, sem segredos. |
| `data/learning_replay_result.json` | Resultado local sanitizado do replay; permanece ignorado pelo Git. |

## Comandos reproduzíveis

```bash
python3 scripts/test_free_market_data.py
python3 scripts/ingest_news.py --symbols BTC/USDT ETH/USDT --database-url sqlite:///data/news_api_test.db
python3 scripts/run_learning_replay.py --symbol BTCUSDT --interval 1h --limit 500 --horizon-bars 8
python3 -m pytest -q
```

O comando de ingestão e os replays usam bancos/arquivos locais ignorados pelo Git. Nenhuma dessas rotinas envia ordens.

## Referências

[1]: https://www.binance.com/en/support/faq/detail/9be58f73e5e14338809e3b705b9687dd "Binance — How to Use Binance Demo Trading?"

[2]: https://developers.binance.com/en/docs/products/spot/testnet/general-info "Binance Developer Docs — Testnet General Info"

[3]: https://developers.binance.com/en/docs/products/spot/rest-api "Binance Developer Docs — General REST API Information"

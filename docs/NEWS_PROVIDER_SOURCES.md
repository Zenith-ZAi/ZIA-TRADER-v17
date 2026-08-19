# Fontes consultadas — provedores de notícias

## Marketaux

Fonte oficial: https://www.marketaux.com/documentation

Endpoint validado: `GET https://api.marketaux.com/v1/news/all`. Autenticação por `api_token` em query. Filtros usados: `symbols`, `filter_entities`, `must_have_entities`, `group_similar`, `language`, `limit`. A resposta usa `data[]` com `uuid`, `title`, `description`, `snippet`, `url`, `published_at`, `source` e `entities[]`; cada entidade pode conter `symbol` e `sentiment_score` entre -1 e 1.

## Finnhub

Fonte oficial: https://finnhub.io/docs/api

Base REST validada: `https://finnhub.io/api/v1`. As requisições GET aceitam `token` na query ou o header `X-Finnhub-Token`. A documentação valida o recurso de market news e a resposta de notícias com `datetime`, `headline`, `related`, `source`, `summary` e `url`. O adaptador usa `/news?category=crypto` para o fluxo cripto.

## Twelve Data

Fontes oficiais: https://twelvedata.com/docs e https://api.twelvedata.com/doc/swagger/openapi.json

Base REST validada: `https://api.twelvedata.com`. A autenticação aceita `apikey` na query ou o header `Authorization: apikey ...`. A documentação geral valida tratamento de `401`, `403`, `404` e `429`, cache e timeouts. Durante a execução de 19/08/2026, o caminho `/news` retornou HTTP 404 para a chave fornecida; o código mantém fallback seguro e registra o provedor como indisponível, sem fabricar artigos.

## Resultado operacional observado

Em 19/08/2026, a ingestão real retornou sucesso para Alpha Vantage, Marketaux, Finnhub, NewsAPI, RSS e CoinGecko; GDELT excedeu o timeout de 8 segundos; Twelve Data retornou 404. As chaves não devem ser incluídas neste arquivo, no Git ou em relatórios.

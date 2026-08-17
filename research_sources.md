# Fontes oficiais para o pipeline de notícias e tendências

## CoinGecko
- Endpoint oficial: `GET /search/trending`.
- A documentação informa que o resultado padrão inclui os 15 criptoativos, 7 NFTs e 6 categorias mais buscados.
- A resposta da documentação informa cache de 10 minutos e que planos Analyst ou superiores podem usar `show_max`.
- Autenticação Pro: header `x-cg-pro-api-key` ou query `x_cg_pro_api_key`.
- Fonte: https://docs.coingecko.com/reference/trending-search

## GDELT
- O projeto informa que sua base é gratuita e aberta.
- As APIs JSON em tempo real incluem DOC, GEO e TV; o GDELT 2.0 atualiza eventos e GKG a cada 15 minutos conforme a página de dados.
- Fonte: https://www.gdeltproject.org/data.html

## Alpha Vantage
- Oferece APIs gratuitas e pagas para mercado, cripto, indicadores técnicos e notícias/sentimento.
- O endpoint intraday exige `function`, `symbol`, `interval` e `apikey`; `compact` devolve os 100 pontos mais recentes e `full` é premium.
- A documentação informa que o endpoint `NEWS_SENTIMENT` pertence ao conjunto de Alpha Intelligence e requer API key.
- Fonte: https://www.alphavantage.co/documentation/
- Fonte: https://www.alphavantage.co/

## Benzinga
- A documentação oficial informa APIs de notícias, mercado e empresas.
- A autenticação é feita com API key no parâmetro de query `token`.
- Para ingestão em tempo real, a documentação recomenda o parâmetro `updatedSince` na News API.
- Fonte: https://docs.benzinga.com/introduction/welcome

## News API
- O endpoint oficial `/v2/everything` exige `apiKey` ou header `X-Api-Key`.
- Permite pesquisar títulos, descrição e conteúdo, filtrar por idioma, ordenar por `publishedAt`, e limita `pageSize` a 100.
- Fonte: https://newsapi.org/docs/endpoints/everything

## CryptoPanic
- A API exige token de autenticação e recomenda não consultar mais de uma vez a cada 30 segundos devido ao cache do serviço.
- A página de planos informa que o Developer API gratuito foi descontinuado em 1º de abril de 2026 e que os planos atuais são pagos.
- A API oferece sentimento e PanicScore, mas deve ser habilitada somente quando houver credencial e plano válido.
- Fonte: https://cryptopanic.com/developers/api/about
- Fonte: https://cryptopanic.com/developers/api/plans

## Sonda executada no ambiente
- CoinGecko respondeu com uma tendência para BTC e foi marcado como provedor saudável.
- RSS respondeu com 20 artigos e funcionou como fallback gratuito de notícias.
- GDELT permaneceu indisponível por timeout de 8 segundos nesta execução; o pipeline não inventou artigos e registrou o provedor como falho.

## Índice oficial Benzinga atualizado
- O índice oficial lista `https://docs.benzinga.com/api-reference/news-api/get-news-items.md` como endpoint de notícias estruturadas e recomenda limitar por tickers/data/canais ou usar `updatedSince` para deltas.
- O mesmo índice lista `https://docs.benzinga.com/api-reference/ticker-trends-api/get-ticker-trend-data.md` e `get-ticker-trend-list-data.md` para tendências de tickers.
- Fonte: https://docs.benzinga.com/llms.txt

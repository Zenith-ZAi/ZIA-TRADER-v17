# Fontes externas — coletor unificado de dados de mercado

Data da consulta: 2026-11-03. Essas fontes descrevem interfaces/capacidades; não homologam dados para trading, garantem disponibilidade, nem concedem direitos de redistribuição. O coletor do projeto deve manter cada fonte separada e guardar origem e horário.

- Binance documenta um domínio de dados públicos sem autenticação com endpoints REST para klines, trades, depth e tickers e streams WebSocket públicos separados. A camada proposta usa somente dados de mercado públicos; não usa User Data Streams nem endpoints de conta/ordem [1].
- CoinGecko enumera endpoints para preços, mercado, histórico, charts, OHLC e tendências. O limite varia por plano; docs atuais informam 100 chamadas/minuto no Demo, limitação por IP sem chave e contagem de respostas de erro para rate limit [2] [3]. Os resultados não são intercambiáveis com book/trades da exchange.
- Alpha Vantage documenta séries diárias raw/as-traded de ações; a opção compacta retorna no máximo 100 pontos e está disponível em chaves free e premium. Intraday e dados em tempo real/atrasados para ações dos EUA têm condições premium/entitlement. A página de suporte informa 25 chamadas/dia no serviço gratuito [4] [5]. O novo adapter restringe-se a diário e chave somente de dados; nunca registra parâmetros/segredos em logs.
- Yahoo Finance é usado por adaptadores existentes do projeto via endpoint de chart, mas yfinance afirma não ser afiliado/endossado pelo Yahoo e indica uso pessoal, pesquisa/educação. Os termos oficiais limitam o acesso automatizado a meios autorizados pelas APIs e atribuem responsabilidade ao usuário. Por isso, o novo coletor não automatiza Yahoo/yfinance até existir autorização/licença e revisão jurídica apropriada [6] [9].
- Supabase Data API exige controles de grants e Row Level Security; não é necessário para este incremento porque o sistema já mantém PostgreSQL local da aplicação [7].
- GDELT DOC é busca de notícias e artigos, não feed de preço/execução. A página consultada é uma introdução datada e não estabelece SLA atual [8].

## Referências

[1]: https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/faqs/market_data_only.md "Binance Market Data Only URLs"
[2]: https://docs.coingecko.com/reference/endpoint-overview "CoinGecko Endpoint Overview"
[3]: https://docs.coingecko.com/docs/common-errors-rate-limit "CoinGecko Errors and Rate Limits"
[4]: https://www.alphavantage.co/documentation/ "Alpha Vantage API Documentation"
[5]: https://www.alphavantage.co/support/ "Alpha Vantage Support and Usage Limits"
[6]: https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apitnc/index.html "Yahoo Application Programming Interface Terms and Conditions"
[7]: https://supabase.com/docs/guides/api/securing-your-api "Securing the Supabase Data API"
[8]: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ "GDELT DOC 2.0 API Overview"
[9]: https://github.com/ranaroussi/yfinance "yfinance project disclaimer and usage notice"

# Fontes consultadas — conectores e ingestão de dados

Data de consulta: 2026-11-02. Estas fontes descrevem capacidades e limites de provedores; não homologam dados para trading nem concedem licença de redistribuição.

- **Alpha Vantage:** a documentação lista APIs para preços, notícias/sentimento, fundamentos, câmbio, criptoativos e indicadores. Cada endpoint tem parâmetros, direitos e limites próprios; dados em tempo real ou intraday podem exigir plano pago/entitlement específico [1]. O projeto já contém um adaptador de notícia opcional por `ALPHA_VANTAGE_API_KEY`; não foi encontrada essa chave no ambiente corrente.
- **CoinGecko:** a documentação oficial informa limites dependentes do plano, 100 chamadas/minuto no Demo e limitação por IP compartilhada sem chave; respostas de erro também contam para o limite [2]. O endpoint de histórico pode retornar preço, capitalização e volume com granularidade dependente da janela/plano [3]. O MCP CoinGecko está disponível para consultas do agente, mas isso não entrega sua autenticação ao processo Python do Trader.
- **GDELT:** a referência oficial DOC 2.0 descreve busca textual, saída JSON e modo de lista de artigos; é uma fonte de cobertura/notícias, não um calendário de consenso econômico ou feed de preços/executáveis [4]. A publicação consultada é de 2017 e não deve ser tratada como SLA atual.

Nenhum segredo foi impresso, copiado para arquivos ou usado em chamadas ao banco. Não foi criada automação nem agendamento externo.

## Referências

[1]: https://www.alphavantage.co/documentation/ "Alpha Vantage API Documentation"
[2]: https://docs.coingecko.com/docs/errors-and-rate-limits "CoinGecko Errors and Rate Limits"
[3]: https://docs.coingecko.com/reference/coins-id-market-chart "CoinGecko Historical Market Chart Endpoint"
[4]: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ "GDELT DOC 2.0 API Overview"

# Relatório final de refinamento — ZIA-TRADER-v17

> **Aviso operacional:** os testes validam software, regras de risco e integração de dados; não comprovam rentabilidade futura, assertividade financeira nem autorizam negociação real sem homologação, sandbox da corretora e aprovação operacional.

## Estado entregue

O refinamento foi implementado, validado e sincronizado no branch `master` do repositório [Zenith-ZAi/ZIA-TRADER-v17](https://github.com/Zenith-ZAi/ZIA-TRADER-v17). O commit publicado é `d866dc71c8700b0fcc5a794bbd9dbf458b67d068`, com a mensagem `feat: harden super engine and hybrid market data pipeline`.

| Área | Resultado aplicado |
|---|---|
| Motor Super | Leitura explicável combinando tendência, momentum, RSI, MACD, volume, sentimento e tendência externa. |
| Sinais bons e ruins | Sinal bom exige ação direcional, confiança mínima, confluência e volatilidade dentro do limite; sinais contraditórios, dados insuficientes ou volatilidade alta retornam `hold`. |
| Backtest | Simulação walk-forward sem look-ahead, com taxas, stop-loss, take-profit, PnL, win rate, profit factor, Sharpe, drawdown e qualidade dos sinais. |
| Risco | Limite de perda diária, risco por operação, exposição por símbolo, exposição total, validação de preço/ação/confiança e bloqueio quando a leitura de posições falha. |
| Notícias | GDELT e RSS como fontes gratuitas; Alpha Vantage, Benzinga, News API e CryptoPanic como integrações opcionais por credencial. |
| Tendências | CoinGecko público/Pro e Benzinga Ticker Trends opcional; cache, timeout, normalização e persistência. |
| Banco | Tabelas `news_articles` e `trend_snapshots`, com deduplicação idempotente de artigos. |
| Menus | O menu de testes só lista suítes existentes; o benchmark não fabrica métricas e o treinamento não reporta sucesso sem dataset OHLCV real. |
| Deploy | `Dockerfile`, `docker-compose.yml`, `worker.py`, `/healthz`, CI no GitHub e autenticação por variáveis de ambiente em produção. |

## Como o motor decide

A leitura é feita em uma janela histórica anterior à barra de decisão. A tendência compara EMAs, o momentum mede os retornos recentes, RSI identifica extensão relativa, MACD avalia diferença entre linha e sinal, volume procura confirmação e ATR normalizado mede volatilidade. Notícias e tendências externas entram como componentes limitados entre `-1` e `1`.

O motor calcula um score ponderado e classifica o regime como `alta`, `baixa`, `transição` ou `lateral`. Uma oportunidade só é considerada boa quando a ação é `buy` ou `sell`, a confiança supera `MIN_CONFIDENCE_THRESHOLD`, não existe contradição relevante entre componentes e a volatilidade está abaixo de `BACKTEST_MAX_VOLATILITY`. Caso contrário, o resultado é `hold`, acompanhado de motivos auditáveis.

A previsão dos modelos também passa por uma **gate de confluência**: quando a ação do modelo e a leitura determinística divergem, a ordem é convertida em `hold`. Essa escolha reduz sinais falsos por excesso de confiança, mas também pode reduzir a frequência de operações.

## Fontes externas e fallback

A fonte gratuita de tendências CoinGecko foi confirmada no ambiente, retornando dados para BTC. O RSS gratuito respondeu com 20 artigos. O GDELT foi consultado, mas excedeu o timeout de 8 segundos nesta execução; o sistema registrou a falha e não fabricou notícias. A documentação oficial do CoinGecko informa o endpoint de tendências, resultados padrão e cache de 10 minutos [1]. O GDELT declara a disponibilidade de dados abertos e APIs JSON em tempo real [2].

As fontes pagas não são chamadas quando a respectiva chave não está configurada. Quando disponíveis, Alpha Vantage fornece notícias/sentimento [3], Benzinga fornece notícias estruturadas pelo endpoint `/api/v2/news` e tendências pelo endpoint `/api/v1/trending-tickers` [4] [5], News API oferece descoberta de artigos pelo `/v2/everything` [6], e CryptoPanic fornece notícias/sentimento/PanicScore conforme o plano contratado [7]. O sistema usa cache e limites configuráveis; credenciais não são versionadas.

## Validação executada

| Verificação | Resultado |
|---|---:|
| Suíte completa | **17 testes aprovados** |
| Testes individuais do menu | Banco 9, API 2, Stress 5, Notícias 1 — todos aprovados |
| Compilação Python | Aprovada |
| `pip check` | Nenhum requisito quebrado |
| `git diff --check` | Aprovado |
| YAML do Compose | Estruturalmente válido |
| `.env` versionado | Não |
| Docker local no sandbox | Não disponível; build será executado pela CI |

A validação cobre autenticação e healthcheck, CRUD do banco, rejeição de volatilidade extrema, backtest determinístico, risco diário e exposição, fallback de fontes, persistência idempotente e provedor pago Benzinga com resposta simulada apenas no teste unitário.

## Checklist para ativação em nuvem

A composição separa a API HTTP do `worker.py`, evitando que múltiplas réplicas HTTP iniciem motores duplicados. Para produção, é obrigatório injetar `POSTGRES_PASSWORD`, `SECRET_KEY`, `AUTH_USERNAME` e `AUTH_PASSWORD`; o Compose usa `AUTH_MODE=env` e `DEMO_AUTH_ENABLED=false`. As chaves de notícias, tendências e exchange são opcionais e devem ser adicionadas somente quando houver licença e necessidade operacional.

O deploy final ainda não foi executado em uma nuvem porque não foi informado um provedor ou uma máquina persistente anexada. A imagem pode ser construída pela CI do GitHub; em uma máquina persistente, ainda devem ser configurados firewall, HTTPS, serviço de auto-inicialização, backups, PostgreSQL gerenciado ou volume persistente e uma exchange em sandbox antes de qualquer modo live. O primeiro deploy recomendado é **paper trading/sandbox**, com `AUTO_START_ENGINES=false` na API e o worker habilitado somente após a verificação de saúde.

## Referências

[1]: https://docs.coingecko.com/reference/trending-search "CoinGecko — Trending Search List"
[2]: https://www.gdeltproject.org/data.html "GDELT Project — Data and APIs"
[3]: https://www.alphavantage.co/documentation/ "Alpha Vantage — API Documentation"
[4]: https://docs.benzinga.com/api-reference/news-api/get-news-items.md "Benzinga — News API"
[5]: https://docs.benzinga.com/api-reference/ticker-trends-api/get-ticker-trend-data.md "Benzinga — Ticker Trend Data"
[6]: https://newsapi.org/docs/endpoints/everything "News API — Everything endpoint"
[7]: https://cryptopanic.com/developers/api/about "CryptoPanic — API overview and plans"

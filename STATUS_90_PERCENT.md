# Status estrutural do ZIA-TRADER-v17

## Classificação atual

O projeto está preparado para **shadow mode supervisionado no VPS**, com maturidade estrutural alvo de aproximadamente **90% para pesquisa, replay, backtest e shadow**. Essa classificação não representa garantia de lucro, prontidão para capital real ou validação de risco de mercado.

## Resolvido e comprovado no Sandbox

| Área | Estado |
|---|---|
| I/O do runtime | Adapters públicos, notícias e coletores usam `httpx.AsyncClient` com pool; a sessão síncrona restante é exclusiva para `FakeSession` de testes do adapter Binance. |
| Circuit breaker/TTL | Implementado por provedor no transporte HTTP, com timeouts separados, cache TTL e semáforo de concorrência. |
| Pullback incremental | Registro por símbolo/timeframe com assinatura de toda a janela e último candle; invalida dados alterados. |
| Redis e concorrência | Instância compartilhada no TradingManager; locks com TTL, renovação, token de owner e liberação condicional. |
| Idempotência | `clientOrderId`, intents persistentes, recuperação após timeout e reconciliação. |
| OCO | Caminho nativo e fallback de duas proteções, com persistência e cancelamento. |
| E2E local | Simulação de 100 ordens com rejeições, timeouts, fills parciais, proteções e reconciliação final consistente. |
| Integridade | SHA-256, validação OHLCV, timestamps, duplicatas, valores inválidos e DecisionSnapshot. |
| Observabilidade | Health detalhado, métricas, regras Prometheus, JSON logs e correlation ID. |
| Perímetro | Nginx TLS de teste, headers de segurança, configuração de firewall em dry-run e documentação de WAF externo. |
| Segurança live | Mainnet, live mode e capital real permanecem bloqueados por defaults e Compose VPS. |

## Itens P2 ainda não resolvidos no Sandbox

1. Histórico completo de order book, trades, spread, profundidade e slippage por ativo e timeframe.
2. Dataset imutável multiativo de cinco anos para BTC, ETH, EURUSD e SPY, com cobertura e licenciamento comprovados.
3. Treinamento massivo com validação cruzada temporal, calibração e modelo aprovado; nenhum resultado deve ser inventado ou promovido sem dados reais.
4. Homologação E2E contra Binance Demo/Testnet com credenciais sandbox próprias, fills parciais, clock drift, cancelamento e reconexão.
5. Testes de caos e restauração real de PostgreSQL/Redis, RPO/RTO e backup externo.
6. TLS público com certificado de autoridade confiável, firewall aplicado no VPS, proxy endurecido e WAF externo.
7. Alertmanager/dashboard/alertas 24/7, SLOs, rotação de segredos, SBOM e scan de vulnerabilidades no pipeline de deploy.
8. Validação de latência de rede, slippage, rate limits e comportamento sob carga de cinco símbolos e três timeframes no VPS real.

## Critério de passagem

O próximo ambiente deve permanecer em `BINANCE_MODE=simulated`, `SHADOW_MODE_ENABLED=true`, `AUTONOMOUS_TRADING_ENABLED=false`, `LIVE_TRADING_ENABLED=false` e `LIVE_MODE=false` até que a revisão humana, a restauração de backup, os testes de Demo/Testnet e o período prolongado de paper/shadow sejam concluídos. A eventual habilitação futura de capital real é uma decisão operacional independente e não está autorizada por este arquivo.

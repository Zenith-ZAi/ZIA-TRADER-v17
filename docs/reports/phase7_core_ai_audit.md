# Auditoria do core de IA e integridade temporal — Fase 7

**Data:** 2026-10-21. **Base:** `861d5f96e808725b3df311382a69da496cf15c98`. **Escopo:** integridade de timestamps, barras fechadas, cotação e causalidade de backtest; preservação das lógicas de sinais e risco.

## Achados reproduzidos e corrigidos

1. **Notícias fora da janela verificável.** Artigos sem timestamp ou com timestamp futuro podiam contribuir para gates/features, e artigos velhos continuavam no sentimento/shock. O `NewsGate` agora usa apenas timestamps parseáveis, não futuros e dentro de `NEWS_MAX_ARTICLE_AGE_SECONDS`; motivos de rejeição ficam distinguíveis. O fail-closed e os thresholds existentes não foram relaxados.
2. **Candle em formação no runtime.** `MultiTimeframeFeed` agora remove somente a última barra cujo intervalo ainda está aberto antes de métricas/imputação/features. Candles futuros permanecem rejeitados, e histórico insuficiente continua bloqueando o ciclo.
3. **Timestamp/proveniência de cotação.** Adapters com tempo de fonte preservam o timestamp do tick; fontes derivadas de OHLCV identificam barra/timeframe; feed rejeita quotes sem origem temporal verificável e aplica limite de idade. Isso não torna fontes públicas/read-only venues executáveis.
4. **Look-ahead no backtest.** A decisão de mercado, pullback, features do Ensemble e assinatura de padrão é limitada à barra fechada anterior (`decision_index=index-1`); execução usa o `open` da barra seguinte. Na inspeção final foi identificado caso adicional: quando a coluna `open` não existia, o helper genérico devolvia o `close` da própria barra de execução. O novo `_next_bar_execution_price()` usa `open` válido; se ausente/inválido, só aceita o close anterior conhecido; se ambos forem inválidos, a barra é descartada. Regressão explícita cobre `open` ausente, `NaN` e válido.

## Não alterado

Não foram alterados cálculo canônico de sinais/indicadores, thresholds, pesos de votação 0.30/0.30/0.40, sizing, limites de risco, autorização `OrderManager`, idempotência, reconciliação, proteções ou flags live. O único ajuste de backtest altera a janela de informação e o preço causal permitido pela simulação; não introduz um sinal novo.

## Evidência

- `tests/test_stress.py::test_backtest_decision_uses_previous_closed_bar_for_next_open` valida os índices de decisão até a barra anterior.
- `tests/test_stress.py::test_backtest_execution_price_falls_back_only_to_previous_close` valida preço de execução sem look-ahead.
- `tests/test_feed_quality.py` e `tests/test_feed_persistence.py` cobrem qualidade/estado de feeds.
- `tests/test_upgrade_core.py::test_news_gate_accepts_fresh_healthy_context` e `test_news_gate_rejects_articles_without_timestamp_or_from_future` cobrem frescor, ausência e futuro de timestamps de notícias.
- Suíte completa no ambiente declarado: **189 passed, 3 skipped, 1 warning**; `compileall` e `git diff --check` passaram. Detalhes em `docs/TEST_EVIDENCE.md`.

## Limitações ainda abertas

- Não há dataset de mercado de procedência verificada nem artefato ativo/aprovado. Não houve treino, avaliação de retorno, calibração de mercado ou promoção.
- Provedores podem não fornecer timestamp parseável; sob fail-closed isso pode reduzir disponibilidade de entradas. Fontes sem tempo verificável não foram aceitas como quote executável.
- Não foi feita conexão externa a broker/exchange, teste Demo/Testnet, deploy VPS ou execução em mainnet.
- Ledger `equity_ledger_v1` e `closed_execution_ledger_v1` ainda não existem; novas entradas permanecem bloqueadas pelo fail-closed.

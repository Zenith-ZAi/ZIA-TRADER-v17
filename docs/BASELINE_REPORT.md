# Baseline Report — Fase 7

**Data:** 2026-10-21 12:09 America/New_York (aprox.)  
**Repositório/ambiente:** `Zenith-ZAi/ZIA-TRADER-v17`, Sandbox Linux, checkout `/home/ubuntu/ZIA-TRADER-v17-remote`  
**Commit base:** `861d5f96e808725b3df311382a69da496cf15c98` (`feat(safety): enforce risk and model contracts (#17)`)  
**Branch no momento da baseline:** `master`; working tree limpo. A branch de trabalho `phase7/core-ai-data-causality` foi criada somente após a validação baseline.

## Comandos e resultados

| Comando | Resultado |
|---|---|
| `/home/ubuntu/.venvs/zia-v17/bin/python --version` | Python 3.12.3 |
| `python -m compileall -q .` | Exit 0; compilação integral concluída sem erro. |
| `python -m pytest -q` | Exit 0; 178 passed, 3 skipped, 1 warning, 49,57 s. |

O warning é `PendingDeprecationWarning` de Starlette sugerindo `python_multipart`. Os 3 testes skipped fazem parte da configuração/suíte atual; nenhum foi removido para esta baseline.

## Artefatos e componentes examinados

- Estado Git e últimos commits: fases 4/5, revisão arquitetural e PR #17 integrada.
- `docs/reports/phase3_status.md`, `phase4_status.md`, `phase5_status.md`, revisão do modelo de 2026-10-08 e relatório de correções de 2026-10-19.
- `docs/FINDINGS.md`, `docs/FEED_QUALITY_PIPELINE.md`, `docs/NEWS_PROVIDER_SOURCES.md`, `docs/AI_TRAINING_AND_VALIDATION.md`, `docs/DATABASE_OPERATIONS.md` e runbook VPS.
- `core/data_feeds.py`, `core/feed_quality.py`, `core/news_gate.py`, `core/engine.py`, `core/backtest_engine.py`, `core/market_signals.py`, `ai/feature_pipeline.py`, adapters relevantes e testes de feed/news/backtest.
- `requirements.txt`, `requirements.lock` e `.github/workflows/ci.yml`.

## Estado herdado já implementado

Fases 1–5 e PR #17 constam integradas no commit base: migrações/backup, controles de qualidade OHLCV, persistência de gaps e order book, treino walk-forward/registry/drift, resiliência/reconciliação de ordens, gates de startup/OrderManager, verificação de artefato/modelo, voto com pesos existentes e limites de risco fail-closed.

Não repetirei essas fases. A Fase 7 desta branch se concentra em integridade temporal da inferência/mercado/notícias e na ausência de look-ahead no backtest. A baseline confirmou código/testes, não prontidão operacional.

## Limitações conhecidas na baseline

- Não foi encontrado dataset de mercado de procedência verificada nem artefato aprovado em `models/`; não haverá novo treino, promoção ou alegação de performance.
- Ledger financeiro completo verificado ainda não existe; novas entradas permanecem bloqueadas pelo fail-closed.
- Live, autonomia, manual real e auto-start permanecem desligados.
- Não foi feita chamada a broker/exchange; teste de dados real, VPS, Demo/Testnet e estado de posição não foram verificados nesta baseline.
- A auditoria identificou como hipóteses reproduzíveis por inspeção (a validar por testes nesta branch): artigos com timestamps ausentes/futuros podem satisfazer o gate de notícias; artigos antigos ainda afetam sentimento; backtest usa features da barra corrente e assume entrada no `open` dessa mesma barra; feeds podem incluir candle em formação. A validade será testada por regressões específicas antes de corrigir.
- Timestamp de cotação tem proveniência inconsistente em adapters; esta lacuna não autoriza considerar cotação válida para execução e será registrada separadamente se não puder ser corrigida sem interromper provedores cuja origem temporal não foi comprovada.

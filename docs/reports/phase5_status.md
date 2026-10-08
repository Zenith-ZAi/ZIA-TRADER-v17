# Fase 5 — Robustez do broker

**Data:** 2026-10-08

**Escopo:** Pre-production / Shadow / Demo / Testnet; mocks em todos os testes.

**Estado:** implementação local concluída e validada; não houve conexão a broker nem execução de ordens reais.

## O que foi alterado

- `core/reconciliation.py` agora reconsulta pela chave idempotente `clientOrderId` intents persistidas em estado `submitted`, `pending`, `open` ou `partially_filled`, antes de reutilizá-las. O status remoto, o ID da exchange e o payload/fill observados são persistidos.
- `OrderReconciler.reconcile()` percorre as intents abertas durante a reconciliação pós-restart. Confirmações atualizam o estado local; ausência, divergência ou estado remoto desconhecido mantém a intent em recuperação pendente.
- `execution/binance_adapter.py` implementa GET read-only `/v3/order` por `origClientOrderId`, com normalização de estados e fills. `ExchangeConnector` e `MarketConnector` expõem a consulta de forma opcional para preservar adapters que não a suportam.
- Antes do auto-start e dos starts manuais, `main` faz reconciliação antes de criar tasks. Falha de consulta ou status diferente de `ok` impede o início; no start manual retorna HTTP 503, e no auto-start registra erro e mantém as engines paradas.
- Se o envio termina em exceção de transporte e nenhuma consulta remota confirma a ordem, a intent permanece `submitted`, o reconciliador retorna `recovery_pending` e não repete automaticamente o POST. Respostas explícitas de erro do adapter ainda seguem o retry limitado existente e usam o mesmo client ID.

Nenhuma lógica de sinais, indicadores, sizing, cálculo/limites de risco ou regras de decisão foi alterada.

## Suíte de falhas

Os testes usam um `FakeBroker`, SQLite temporário e `FakeSession`; não chamam a rede nem precisam de credenciais reais. Os cenários incluem:

1. Timeout após aceitação remota: localizar a ordem pelo client ID e recuperar sem segundo envio.
2. Timeout com estado remoto inconclusivo: preservar `submitted`, retornar `recovery_pending` e não repetir o envio.
3. Reinício com intent `submitted`: reconsultar a exchange e persistir o estado remoto, inclusive fill parcial/terminal.
4. Sweep de intents abertas em `reconcile()` após restart; estado não confirmado gera `attention`.
5. Fill parcial evoluindo para filled sem nova submissão.
6. Chamada duplicada após fill não gera outro envio.
7. Gate pré-start: uma reconciliação que requer atenção impede criar a task da engine.
8. Consulta Binance por `origClientOrderId` validada com sessão HTTP fake.
9. Reconexão do WebSocket existente do dashboard testada ao fechar e reabrir a sessão autenticada.

**Limite importante:** o repositório não contém cliente/stream WebSocket de broker. O cenário 9 cobre apenas o dashboard; não representa reconexão de stream da exchange.

## Validação local

- `python3 -m compileall -q core execution tests`: passou.
- `git diff --check`: passou.
- `python -m pytest -q`: **142 passed, 3 skipped** (26,46 s).
- Baseline documentado após Fase 4: **132 passed, 3 skipped**. A contagem subiu em 10 testes, sem regressão local.

## Limitações e próximos passos

- Não foi executado ensaio em VPS, PostgreSQL real, Binance Demo/Testnet ou qualquer mainnet. A consulta REST foi validada exclusivamente por fake.
- Quando não há confirmação remota, o fluxo é deliberadamente fail-closed: a intent segue pendente e o start das engines é bloqueado até intervenção/reconciliação.
- Foi verificado que `execution/mainnet_adapter.py::BinanceMainnetAdapter.place_order` não recebe/propaga `client_order_id`. Esse caminho está fora do escopo Demo/Testnet e não foi alterado; **manter `LIVE_TRADING_ENABLED=false` e `LIVE_MODE=false`** até correção e validação separadas.
- Os números acima são da sandbox local; os checks remotos publicados na PR desta fase são a referência para validação CI/PostgreSQL.

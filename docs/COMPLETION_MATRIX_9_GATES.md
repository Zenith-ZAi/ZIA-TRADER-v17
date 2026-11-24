# Matriz de conclusão — gates finais ZIA-TRADER-v17

Estado verificado no commit base `360073b288dacc48367e33f7d0c29835ed43d1e5`.

| Layer ID | Camada | Status anterior | Status atual | Evidência / próximos critérios |
|---|---|---|---|---|
| P0-01 | Dados OHLCV, qualidade e gaps | Histórico structural | IMPLEMENTED | Testes de gaps, duplicatas, stale e OHLCV já existentes; centralização adicional nesta PR |
| P0-02 | Backfill histórico idempotente | NOT_STARTED | IMPLEMENTED | Plano de janelas, restart por estado existente e upsert do DatabaseManager |
| P0-03 | Identidade local verificada | PARCIAL | IN_PROGRESS | Foundation tenant/principal/client-scope existe; falta registro, recuperação e sessões revogáveis |
| P0-04 | MFA/Passkey | NOT_STARTED | NOT_STARTED | Sem interface PAD/WebAuthn funcional |
| P0-05 | Vault de credenciais | NOT_STARTED | NOT_STARTED | Credenciais ainda usam settings/ambiente |
| P0-06 | Gateway de Exchange | NOT_STARTED | NOT_STARTED | Adapters existem, mas falta a autorização por credential vault |
| P0-07 | Ledger financeiro autoritativo | PARCIAL | BLOCKED | `equity_ledger_v1` é audit-only e Kelly permanece bloqueado |
| P0-08 | Observer contínuo | PARCIAL | IN_PROGRESS | Collector existe; falta separação completa, observabilidade persistente e backfill contínuo |
| P0-09 | Testnet / operação | PARCIAL | IN_PROGRESS | Execution/reconciliation existem, faltam homologação E2E e evidência externa |

Os gates P0-03 a P0-09 permanecem dependentes de implementação e evidência posterior. Nenhum gate pode ser marcado ACCEPTED sem testes executados e commit/PR verificável.

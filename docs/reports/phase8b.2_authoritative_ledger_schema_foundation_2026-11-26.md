# Fase 8B.2 — Fundamento do ledger autoritativo (schema-only)

**Data:** 2026-11-26
**Branch:** `feature/gate-authoritative-ledger-foundation`
**Base:** `master` pós-PR #34 (`360073b`)
**Estado:** PR [#38](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/38) aberta / **OPEN / NOT ACCEPTED**. Esta subfase não conclui o gate financeiro e não autoriza sizing, entrada, deploy ou operação.

## O que foi implementado

Migration aditiva `d8a11c4e52f0` cria cinco relações tipadas, distintas do `equity_ledger_v1` audit-only:

- `ledger_scope_v1`: liga um escopo financeiro a uma conta de broker persistida e impede reuso de uma conta em mais de um scope;
- `ledger_fact_v1`: fatos candidatos de fill, fee, funding e cashflow, com quantias `NUMERIC(38,18)`, timestamps timezone-aware, IDs remotos e constraints por tipo;
- `ledger_coverage_manifest_v1`: intervalo, cursor, ativos esperados e status; a constraint força `complete=false` nesta fase, até um reconciliador independente existir;
- `ledger_balance_snapshot_v1`: saldo por ativo e referência composta ao manifesto do mesmo scope; exige valores não negativos, mas não compara a soma dos componentes no banco;
- `ledger_period_closure_v1`: registro imutável que só admite `open`/`attention`; `closed` e `closed_at_utc` são deliberadamente proibidos nesta fundação.

As cinco tabelas rejeitam UPDATE/DELETE via triggers no SQLite/PostgreSQL; PostgreSQL também rejeita TRUNCATE. O caminho SQLite `create_all()` de `DatabaseManager` e `init_db()` instala os mesmos guards, e os engines SQLite ativam `PRAGMA foreign_keys` e `recursive_triggers` para todas as conexões. A migration não adota tabelas preexistentes e o downgrade para se qualquer tabela contiver evidência. As entidades ORM foram adicionadas ao metadata para que o schema de testes e a migration tenham contratos equivalentes.

SQLite converte `NUMERIC` por afinidade aproximada; por isso, a migration/ORM não impõe uma comparação aritmética `total = free + locked` que pode rejeitar valores decimais corretos como `0.1 + 0.2 = 0.3`. Essa relação exata deverá ser validada com `Decimal` por um writer/reconciliador futuro antes de qualquer snapshot poder apoiar risco. Testes SQLite demonstram apenas comportamento de schema/constraints, não precisão financeira nem preservação de 18 casas decimais; `NUMERIC(38,18)` no schema, isoladamente, não é prova de exatidão.

Os caminhos SQLite suportados para criação de schema são `DatabaseManager.create_tables()` e `database.init_db(engine)`. O uso direto de `Base.metadata.create_all()` é restrito a fixtures de migração/testes que não aleguem guards equivalentes; não deve inicializar um ledger consumido pela aplicação.

## Verificações executadas

- testes novos + ledger/migrations existentes + contrato fail-closed RiskAI (`test_authoritative_ledger_foundation.py`, `test_equity_ledger_migrations.py`, `test_equity_ledger.py`, `test_risk_period_kelly_contract.py`): **23 passed, 1 skipped**; o skip requer PostgreSQL;
- regressões adjacentes de client scope, `DatabaseManager` e migrations (`test_client_scope.py`, `test_database_manager.py`, `test_database_migrations.py`): **20 passed, 1 skipped**. Rodada combinada final: **43 passed, 2 skipped**; ambos os skips dependem de `TEST_DATABASE_URL`/PostgreSQL.
- migration completa Alembic em SQLite de teste, incluindo as cinco tabelas novas;
- casos cobertos: registro/scoping, imutabilidade, tentativa de completar coverage, closure prematura, fill sem IDs/quantidade/preço, recusa de schema preexistente e downgrade com dados; os novos testes exercitam os dois caminhos SQLite `create_all()`, FK composta que cruza scopes, saldo `0.1 + 0.2 = 0.3` sem falsa rejeição, saldo negativo e triggers;
- `compileall` dos arquivos alterados, `git diff --check` e verificação Alembic (head único `d8a11c4e52f0`, predecessor `c3f1e2a9b7d4`): passaram;
- nenhum acesso a Exchange, credential, endpoint privado, ordem ou capital ocorreu.
- a suíte completa do repositório não pôde ser coletada nesta virtualenv temporária focada: faltam `pandas` e `torch` (47 erros de importação/coleta); os testes focados e vizinhos acima foram executados separadamente. CI do PR deve executar a suíte completa com dependências do projeto.

## Limites que mantêm o gate aberto

Este incremento é schema-only. Não há writer financeiro autenticado, adapter produtor homologado, coleta real de fills/fees/funding/cashflows, paginação/cursor recuperável, reconciliação independente, detecção de late events, política de privilégios PostgreSQL ou teste de restart/recovery. SQLite é usado somente como backend de teste/desenvolvimento e não comprova precisão decimal do storage; o writer/reconciliador futuro deve validar com `Decimal` tanto escala como a identidade entre total e componentes. Um digest SHA-256 continua sendo integridade do payload, nunca prova de origem.

As tabelas novas não têm produtor ligado. `get_verified_risk_periods()` e `get_verified_trade_returns()` permanecem indisponíveis (`None`); não foi criado `closed_execution_ledger_v1`, não se lê nenhum desses registros para cálculo de risco/Kelly e nenhum código de execução/ordem, peso de modelo ou flag foi alterado. O próprio schema impede `complete=true` e `status='closed'` nesta fase; uma migration futura só deve relaxar esse bloqueio após o writer/reconciliador e os grants independentes serem revisados.

**Decisão:** o gate “Ledger financeiro autoritativo” permanece **OPEN / NOT ACCEPTED**. `docs/progress/zt01_current_2026-11-19.json` permanece um snapshot histórico de 7/16 na baseline então registrada e não foi recalculado nem atualizado por esta subfase.

## Alinhamento por etapas

A ordem proposta no roadmap continua coerente com os quatro bloqueios indicados pelo operador:

1. **Ledger / reconciliação financeira (Fase 8B):** este PR inicia apenas schema; depois exige writer confiável, ingestão por fonte allowlisted, cobertura/cursor, fechamento independente e recuperação após restart.
2. **Dados e modelo aprovado (Fase 8C):** depende de fonte/licença, dataset rastreável e validação OOS; precisa ter aceite próprio e não pode ser inferido da existência do schema ou de testes sintéticos.
3. **Operação distribuída (Fases 8D/8E/8F):** staging persistente, worker/supervisão, Redis/PostgreSQL, restart/restore, Testnet supervisionada, fault injection e soak têm evidência externa própria; CI/SQLite não equivale a homologação.
4. **Aceite integrado final (Fase 8F):** somente após as etapas anteriores, com evidência ponta a ponta, revisão independente, runbooks e aceite humano explícito. O aceite não será automático por merge.

Os drafts #35–#37 não são usados como base desta mudança. Esta branch deriva diretamente do `master` estável pós-PR #34 para não depender da pilha de PRs ainda não integrada. A sequência segue um gate por cessão: nenhum dos gates posteriores é alterado ou marcado como concluído aqui.

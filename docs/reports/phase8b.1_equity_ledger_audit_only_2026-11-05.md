# Phase 8B.1 — Fundamento do ledger financeiro audit-only

**Data da validação:** 2026-11-06
**Branch:** `feat/audit-only-equity-ledger-8b`
**Base de código:** squash merge da Phase 10.2, `16a7326deb373a477d2ece003de657168ae7f9a2`
**Status:** fundação implementada e validada localmente; **não homologada para risco, reconciliação financeira ou operação**.

## Objetivo e limite

Estabelecer um armazenamento append-only para evidências financeiras reportadas por uma fonte, sem reutilizar o estado mutável de conta como verdade contábil e sem expor o ledger ao caminho de sizing/ordens. Este incremento não conecta exchanges, não obtém saldos/fills, não cria endpoint de escrita e não calcula equity, retorno, lucro/prejuízo ou resultado de execução fechada.

## Alterações

- `equity_ledger_v1` é criada por migration aditiva Alembic `a5c74e8d2b91`, após `4f9a2c7d1b63`. O schema usa `NUMERIC(38,18)`, timestamps UTC, identidade `(account_id, source, source_event_id, line_no)`, eventos por ativo/leg, constraints de tipo e separação semântica entre snapshots (`balance`) e deltas (`delta`). A migration recusa tabela preexistente não versionada em vez de adotá-la ou removê-la silenciosamente. Downgrade recusa qualquer linha; no PostgreSQL adquire `ACCESS EXCLUSIVE` antes de contar/remover, e no SQLite inicia transação exclusiva.
- `append_equity_ledger_event` requer opt-in independente, aceita apenas `Decimal` ou texto decimal (nunca float), rejeita NaN/Infinity, precisão acima de 18 casas, timestamp sem timezone, identificadores inválidos e deltas zero. Replays com payload equivalente são idempotentes; reuso da identidade com conteúdo canônico diferente falha sem sobrescrever. O SHA-256 detecta divergência do payload da chave; **não** é hash-chain, assinatura, atestado do provedor ou prova de autenticidade.
- O método de leitura é paginado e limitado, devolve evidência bruta normalizada e não agrega saldos.
- `EQUITY_LEDGER_CAPTURE_ENABLED=false` é o default no `.env.example`/settings. O lifespan aplica a flag antes do startup; se captura estiver habilitada e o banco injetado não suportar o contrato, startup falha e libera o engine.
- PostgreSQL instala triggers para UPDATE/DELETE e TRUNCATE. SQLite é somente ambiente de teste/desenvolvimento: as conexões gerenciadas ativam `PRAGMA recursive_triggers=ON` para que `INSERT OR REPLACE` acione o trigger de remoção; migration e runtime mantêm os triggers de UPDATE/DELETE. Um processo com acesso direto ao arquivo ou que abra SQLite com configuração diferente não recebe a mesma fronteira de segurança de privilégios do PostgreSQL. **SQLite não é armazenamento inviolável.**
- `get_verified_risk_periods` e `get_verified_trade_returns` continuam retornando `None`. RiskAI continua em fail-closed sem ledger verificável; `closed_execution_ledger_v1` não existe. Nenhum código de trading/ordem, pesos, limites, credenciais ou defaults LIVE foi habilitado ou alterado.

## Revisão e correções

Uma revisão independente encontrou pontos que foram corrigidos nesta branch:

1. Downgrade poderia contar e descartar dados concorrentes: agora o PostgreSQL bloqueia a tabela em modo exclusivo antes da checagem; SQLite usa lock exclusivo durante o downgrade.
2. `INSERT OR REPLACE` podia contornar os triggers SQLite com o default de `recursive_triggers`: conexões SQLAlchemy gerenciadas e a conexão da migration ativam a opção; teste de regressão comprova rejeição e preservação do evento.
3. Um runtime injetado sem setter poderia ignorar captura explicitamente habilitada: agora o startup falha fechado e dispõe o engine; há teste do caminho de erro.
4. A cobertura PostgreSQL não exercitava TRUNCATE; a integração opcional agora tenta UPDATE, DELETE e TRUNCATE.
5. A migration podia assumir ownership de tabela vazia preexistente; agora falha antes de tocá-la, coberto por teste SQLite.
6. O teste PostgreSQL imutável deixaria evento após execução: foi alterado para executar o writer dentro de savepoint/transaction externa e reverter a evidência de teste.

## Verificações locais (2026-11-06)

- Suíte integral: **266 passed, 4 skipped, 1 warning** em 17,81s.
- Os quatro skips requerem `TEST_DATABASE_URL`: migration PostgreSQL, precisão/imutabilidade do ledger, registry PostgreSQL e backup/restore PostgreSQL. Assim, os testes PostgreSQL adicionados **não foram executados nesta sandbox**; precisam passar no CI com serviço PostgreSQL antes de aprovar integração.
- Suíte direcionada: **26 passed, 2 skipped, 1 warning** para ledger, migrations, lifecycle e fail-closed de risco.
- `uv pip check`: 117 pacotes, sem incompatibilidades.
- `compileall`, `git diff --check` e Alembic (`a5c74e8d2b91` como único head): passaram.
- Scanner AST heurístico do repositório: nenhum padrão suportado detectado. Isso não substitui SAST/DAST nem revisão independente.

## Riscos/gates ainda abertos

- A branch precisa de validação PostgreSQL real no CI (incluindo NUMERIC, append-only/TRUNCATE, migration e rollback) e de revisão humana do diff final.
- Nenhum producer/adapter autenticado homologado alimenta o ledger; dados enviados ao método são declarações do chamador. A imutabilidade do banco não garante completude, origem legítima, sequência sem lacunas ou ausência de evento tardio.
- Ainda faltam tratamento de fills parciais/duplicados/tardios, taxas multi-moeda, funding, depósitos/saques, posições, snapshots completos, reconstrução após restart, reconciliação independente, concorrência sob carga, retenção/backup e privilégios PostgreSQL separados para aplicação/migration.
- `closed_execution_ledger_v1` e integração com RiskAI/kelly são etapas futuras e requerem revisão de domínio, evidência read-only/Demo e contrato independente. Nenhum resultado desta subfase autoriza dimensionamento, novas entradas ou operação real.
- `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, `AUTO_START_ENGINES=false`, `AUTONOMOUS_TRADING_ENABLED=false` e `MANUAL_TRADING_ENABLED=false` permanecem obrigatórios.

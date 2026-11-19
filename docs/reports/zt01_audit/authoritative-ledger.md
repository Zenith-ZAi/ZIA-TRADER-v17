# Auditoria read-only — ledger financeiro autoritativo e reconciliação

**Schema do relatório:** `authoritative-ledger`
**Checkout auditado:** `/home/ubuntu/ZIA-TRADER-v17-phase9-resume`
**HEAD auditado:** `09ea8c8e3db23aaf5ae6ebc1406f75a379f25912` (`fix/backend-provider-security-nov19`)
**Escopo:** somente ledger audit-only, getters `get_verified_risk_periods`/`get_verified_trade_returns`, intents, evidência de fills, reconciliação e adapters existentes. Nenhum código, flag, menu ou configuração foi alterado; não houve browser, credencial real, request privado ou envio de ordem.

## Decisão de auditoria

A base é adequada para **evidência audit-only e bloqueio fail-closed**, mas não contém ainda um fato financeiro autoritativo por `(account_id, venue, environment)`. O incremento mínimo seguinte deve criar uma fronteira de ingestão autenticada e um journal de fatos imutáveis, sem ligar os getters ao sizing. Até que haja fechamento de período e reconciliação independente, os dois getters devem continuar retornando `None`/indisponível; nenhum `market_context`, array do caller, hash ou campo `source` fornecido pelo caller pode ser promovido a “verificado”.

A suíte local executada no virtualenv, sem rede, foi:

```text
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_equity_ledger.py tests/test_equity_ledger_migrations.py \
  tests/test_risk_period_kelly_contract.py tests/test_phase5_broker_resilience.py \
  tests/test_execution_persistence.py
39 passed, 1 skipped
```

Esse resultado comprova os guards atualmente testados, não autenticidade de corretora, completude financeira, rentabilidade, reconciliação de saldo ou readiness operacional.

## Inventário factual atual

- `equity_ledger_v1` existe via migration `a5c74e8d2b91` e é append-only. Aceita `balance_snapshot`, `trade_fill`, `fee`, `funding`, `cashflow` e `reconciliation_adjustment`, usa `NUMERIC(38,18)`, exige `Decimal`/texto decimal e timestamp com timezone no writer. A própria documentação declara que ele é somente evidência reportada e que seu SHA-256 não é assinatura, atestado do provedor ou prova de autenticidade (`database_manager.py:336-356`; `docs/reports/phase8b.1_equity_ledger_audit_only_2026-11-05.md:14-19`).
- `get_verified_risk_periods` e `get_verified_trade_returns` são stubs que sempre retornam `None` (`database_manager.py:317-334`). Isto está correto e deve ser preservado neste incremento.
- O modelo não contém `closed_execution_ledger_v1`, `fill_evidence` ou tabela de fills por trade. O inventário de tabelas confirma apenas `execution_history`, `order_intents`, posições e o ledger audit-only.
- `OrderIntent` guarda quantidade/preço em `Float`, um único status mutável, `exchange_order_id`, tentativas e `payload_json` (`database.py:320-337`). A reserva é idempotente por `client_order_id`, mas não fixa venue/environment nem uma sequência append-only de respostas.
- `ExecutionHistory` também usa `Float` para preço, quantidade e comissão e não guarda asset da fee, trade ID remoto, venue, environment ou timestamp de fonte (`database.py:134-148`). O `ExecutionEngine` apenas cria/fecha posição e trata persistência como best-effort (`execution/execution_engine.py:14-20`, `60-101`); não transforma resposta de fill em fatos financeiros.
- O `OrderReconciler` consulta `client_order_id`, persiste status e bloqueia retry ambíguo/restart (`core/reconciliation.py:158-296`), mas não coleta cada fill, fee, funding, cashflow ou saldo completo.
- Binance Testnet/Demo é o único adapter real de execução com caminho implementado. `place_order` retorna quantidade/preço agregados, soma `commission` como número e mantém `raw` no payload (`execution/binance_adapter.py:316-362`); a busca por `client_order_id` não retorna fees nem lista de fills (`:378-413`). Mainnet continua bloqueada por gates. Forex live e MT5 live bloqueiam; Forex paper e `SimulatedExchangeAdapter` são sintéticos. O FIX adapter ainda marca-se conectado e devolve `pending_fix`/`clordid` sintético sem sessão de corretora real (`execution/fix_adapter.py:25-65`), portanto não pode ser fonte autorizada de fatos.

## Achados materiais — máximo de cinco

### A1 — O ledger audit-only não tem uma fronteira de confiança autoritativa

**Evidência:** a chave atual é `(account_id, source, source_event_id, line_no)` (`database.py:155-157`), sem `venue` ou `environment`. `append_equity_ledger_event` recebe do chamador `account_id`, `source`, `source_event_id`, tipo, ativo, valor e `occurred_at`, e a docstring afirma explicitamente “source-reported evidence only” (`database_manager.py:336-356`). O hash é calculado sobre o payload canônico (`:425-443`) e serve para detectar reuso divergente (`:479-482`), não para autenticar quem reportou o valor.

**Blocker concreto:** qualquer código autorizado a chamar o método pode declarar um saldo, fill, fee ou funding com um `source` arbitrário e um timestamp passado. Imutabilidade impede alteração posterior, mas não impede inserção falsa, lacuna, atraso ou omissão. Sem escopo `(account_id, venue, environment)` a mesma identidade econômica também não fica separada entre Binance Testnet, Binance Demo, paper ou live.

**Regra de confiança:** o writer autoritativo não pode ser um append público que aceite dict do caller. Deve aceitar somente um objeto emitido por adapter autenticado/allowlisted, com contexto de conta/venue/environment resolvido no servidor e não substituível pelo payload. Hash/digest pode ser evidência de integridade do registro bruto, nunca prova isolada de autenticidade.

### A2 — Intents e adapters não produzem evidência de fill fechada por trade

**Evidência:** intents só têm quantidade/preço solicitados, status, IDs e payload mutável; não há entidade para cada execução parcial. O `ExecutionHistory` é agregado e em `Float`, com uma comissão escalar sem moeda. Binance calcula `filled_price` por `cummulativeQuoteQty/executedQty` e soma `fills[].commission`, descartando no modelo o `tradeId`, a moeda da comissão, cada quantidade/preço individual e seu timestamp. O lookup posterior por client ID também só devolve quantidade/preço agregados. O reconciliador atualiza status da intent, mas não insere nenhuma linha financeira por fill.

**Blocker concreto:** uma ordem parcialmente executada, cancelada e depois completada pode ser vista como um status final, mas não há prova persistida de quais trades compõem o total nem como fees foram cobradas. Isso impede retorno realizado, custo líquido e reconciliação contra saldo. `closed_execution_ledger_v1` não existe; portanto `get_verified_trade_returns` corretamente não pode retornar amostras.

**Adapters que não podem ser produtores agora:** paper/simulação geram valores sintéticos; Forex live e MT5 live falham fechado; FIX tem comportamento stub que não prova envio nem fill. Mesmo Binance Testnet/Demo carece de ingestão read-only de fills/account trades e reconciliação após restart. Mainnet não foi homologada e permanece fora do escopo.

### A3 — Fee, funding, cashflow e completude de saldo são apenas rótulos, não fatos fecháveis

**Evidência:** o schema audit-only permite os tipos `fee`, `funding` e `cashflow`, mas todos compartilham apenas `asset`, `amount`, `occurred_at` e referência genérica. Não existem campos obrigatórios para `fee_asset`, trade/order remoto, funding interval/rate/side, depósito/saque/transferência, estado settled, snapshot ID, cursor ou cobertura de ativos. `balance_snapshot` exige somente `balance_component`, sem manifesto que diga quais ativos/endpoints foram cobertos. As tabelas `daily_pnl`, `weekly_pnl` e `monthly_pnl` são mutáveis e usam `Float`; o próprio getter recusa tratá-las como verdade (`database_manager.py:317-324`).

**Blocker concreto:** não é possível demonstrar binariamente que, para um período UTC, todos os fills, fees, funding e fluxos externos foram incluídos, nem que `closing_balance = opening_balance + deltas` por ativo. Também não se consegue distinguir “zero observado” de “ativo não consultado” sem um manifesto de cobertura. Sem cashflows externos e valuation com preço temporalmente proveniente, starting equity e P&L são indeterminados.

**Requisito:** um período só pode ser fechado quando existir snapshot inicial e final por ativo do escopo, manifesto de cobertura completo, cursor/sequence sem gap, todos os fatos até o watermark, fees/funding/cashflows tipados e uma reconciliação independente que passe exatamente em `Decimal` por ativo. Qualquer desconhecido, timeout, lacuna, ativo não coberto ou evento tardio mantém o período `attention`, nunca `verified`.

### A4 — Decimal, UTC, idempotência e restart não atravessam o caminho inteiro

**Evidência:** a camada audit-only faz o correto localmente: rejeita `float`, normaliza timestamp aware para UTC e instala guards append-only. Porém intents, posições, `ExecutionHistory` e adapters convertem quantidades, preços e comissões para `float` (`database.py:55-65`, `:134-148`; `execution/execution_engine.py:152-189`; `execution/binance_adapter.py:349-360`). `utc_now()` do schema legado remove `tzinfo` (`database.py:27-29`). A chave do ledger não inclui venue/environment. O mapa `_order_symbols` usado por `get_order_status`/`cancel_order` é memória do processo (`binance_adapter.py:66-70`, `:364-376`); após restart, o lookup por client ID pode recuperar uma intent, mas não há coleção durável de fills/fees/cursor para reconstrução.

**Blocker concreto:** exactidão financeira e identidade econômica ficam dependentes de uma resposta agregada em float e de estado volátil. O fluxo de retry evita duplicar ordem em muitos casos, mas isso não equivale a idempotência do fato financeiro: não há unique remoto por `venue_trade_id`, sequência de fill, nem replay de janela após restart. `payload_json` também é substituído nas atualizações da intent, não é uma trilha imutável de eventos.

**Requisito:** todos os fatos econômicos e campos derivados de valor devem ser `NUMERIC(38,18)`/`Decimal`; timestamps de fonte e ingestão devem ser `TIMESTAMPTZ`/UTC; identidade deve incluir escopo, tipo de evento, ID remoto e linha. Estado ambíguo após timeout/restart deve bloquear e abrir reconciliação, não inferir “sem ordem” nem “fill completo”.

### A5 — A suíte prova guards, mas não prova autoridade; testes atuais podem simular autoattestation

**Evidência:** os testes de risco substituem `db.get_verified_risk_periods`/`get_verified_trade_returns` por lambdas que devolvem dicionários montados no próprio teste com `source: equity_ledger_v1` ou `source: closed_execution_ledger_v1` (`tests/test_risk_period_kelly_contract.py:20-36`, `:113-128`). O `RiskAI` valida forma, flags, IDs, ordem cronológica e idade das amostras (`risk/risk_ai.py:175-223`), mas não tem como distinguir esse dicionário autoatestado de uma consulta canônica ao banco. Em produção os getters continuam `None`, o que preserva o bloqueio; o problema é o contrato futuro de confiança, não uma liberação atual.

**Blocker concreto:** implementar o getter aceitando snapshot/returns vindos de caller, contexto de mercado, JSON de intent ou apenas `source`/hash reproduziria uma falsa verificação. A existência de testes com monkeypatch não pode ser usada como evidência de ledger autoritativo.

**Requisito:** os futuros getters devem ser funções de leitura privadas do módulo de autoridade, com parâmetros apenas de escopo e `as_of/limit`; devem consultar somente linhas persistidas cujo `authority_status` tenha sido produzido pelo reconciliador independente. Não devem aceitar payload, amostras, flags de verificação, fonte, hash ou `ledger_consistent` do caller. Até os critérios de fechamento abaixo passarem, o resultado deve permanecer `None` e o teste deve provar isso mesmo com todos os dados falsos fornecidos no `market_context`.

## Incremento mínimo recomendado: módulo sem sizing

Não alterar o significado de `equity_ledger_v1` nem ligar os getters nesta etapa. Criar primeiro um módulo isolado, por exemplo `authoritative_ledger_v1`, com writer privado de ingestão e migration aditiva. O módulo deve ter quatro relações mínimas; a separação evita esconder invariantes econômicas em JSON:

### 1. Escopo da conta

`ledger_scope_v1`:

```text
scope_id              UUID PRIMARY KEY
account_id            TEXT NOT NULL
venue                 TEXT NOT NULL              -- ex.: binance
environment           TEXT NOT NULL              -- testnet | demo | paper | live
base_asset            TEXT NOT NULL
created_at_utc        TIMESTAMPTZ NOT NULL
UNIQUE (account_id, venue, environment)
```

`venue` e `environment` vêm da configuração/adapter autenticado, não do body financeiro recebido. Nunca misturar paper, testnet, demo e live no mesmo scope.

### 2. Fatos financeiros imutáveis

`ledger_fact_v1` deve ser append-only, com uma linha por fato econômico ou linha de fato:

```text
fact_id               UUID PRIMARY KEY
scope_id              UUID NOT NULL REFERENCES ledger_scope_v1
fact_type             TEXT NOT NULL  -- fill | fee | funding | cashflow
source_event_id       TEXT NOT NULL
source_line_no        INTEGER NOT NULL DEFAULT 0
source_sequence       BIGINT NULL
asset                 TEXT NOT NULL
amount                NUMERIC(38,18) NOT NULL
occurred_at_utc       TIMESTAMPTZ NOT NULL
ingested_at_utc       TIMESTAMPTZ NOT NULL
client_order_id       TEXT NULL
venue_order_id        TEXT NULL
venue_trade_id        TEXT NULL
symbol                TEXT NULL
side                  TEXT NULL
quantity              NUMERIC(38,18) NULL
price                 NUMERIC(38,18) NULL
fee_asset             TEXT NULL
fee_amount            NUMERIC(38,18) NULL
funding_period_start  TIMESTAMPTZ NULL
funding_period_end    TIMESTAMPTZ NULL
funding_rate          NUMERIC(38,18) NULL
cashflow_kind         TEXT NULL       -- deposit | withdrawal | transfer
external_reference    TEXT NULL
adapter_name          TEXT NOT NULL
adapter_version       TEXT NOT NULL
raw_evidence_ref      TEXT NULL       -- referência controlada, sem segredo
raw_evidence_sha256   CHAR(64) NULL   -- integridade, não autenticação
UNIQUE (scope_id, fact_type, source_event_id, source_line_no)
```

Para `fill`, exigir `venue_order_id`, `venue_trade_id`, símbolo, side, quantidade, preço, `occurred_at_utc` e `source_event_id`. Para `fee`, exigir `fee_asset` e `fee_amount` e ligar ao trade/order quando o venue fornecer a ligação. Para `funding`, exigir intervalo UTC, taxa se o venue a fornecer e sinal/asset sem conversão implícita. Para `cashflow`, exigir `cashflow_kind`, referência externa e estado de liquidação antes de entrar num fechamento. Constraints de tipo devem rejeitar combinações incompletas; não aceitar `float`, NaN, infinito, timestamp naive ou quantia zero quando o fato é delta.

A unique deve produzir “duplicate/no-op” para replay byte-a-byte normalizado e “conflict” sem overwrite para a mesma identidade com qualquer campo financeiro diferente. Uma mesma ordem parcial deve ter vários `venue_trade_id`; a soma em `Decimal` só pode ser derivada, nunca substituir as linhas de fill.

### 3. Manifesto de saldos e cobertura

`ledger_balance_snapshot_v1`:

```text
snapshot_id           UUID NOT NULL
scope_id              UUID NOT NULL REFERENCES ledger_scope_v1
asset                 TEXT NOT NULL
free_amount           NUMERIC(38,18) NOT NULL
locked_amount         NUMERIC(38,18) NOT NULL
total_amount          NUMERIC(38,18) NOT NULL
as_of_utc             TIMESTAMPTZ NOT NULL
ingested_at_utc       TIMESTAMPTZ NOT NULL
source_cursor         TEXT NOT NULL
coverage_manifest_id  UUID NOT NULL
UNIQUE (scope_id, snapshot_id, asset)
```

`ledger_coverage_manifest_v1` guarda `manifest_id`, scope, endpoint/stream, `requested_at_utc`, `received_at_utc`, cursor inicial/final, intervalo coberto, conjunto esperado de ativos ou declaração explícita de “all assets”, `complete` e `reconciliation_status`. `complete=true` só pode ser escrito pelo reconciliador após paginação encerrada, cursor sem gap, resposta autenticada e presença explícita de zero para ativos consultados. Sem manifesto, um snapshot não fecha período.

### 4. Fechamento independente, ainda não consumido pelo risco

`ledger_period_closure_v1`:

```text
closure_id            UUID PRIMARY KEY
scope_id              UUID NOT NULL
period_start_utc      TIMESTAMPTZ NOT NULL
period_end_utc        TIMESTAMPTZ NOT NULL
opening_snapshot_id   UUID NOT NULL
closing_snapshot_id   UUID NOT NULL
fact_watermark_utc    TIMESTAMPTZ NOT NULL
fact_count             INTEGER NOT NULL
missing_count          INTEGER NOT NULL
late_count             INTEGER NOT NULL
fees_included         BOOLEAN NOT NULL
funding_included      BOOLEAN NOT NULL
cashflows_reconciled  BOOLEAN NOT NULL
balances_reconciled   BOOLEAN NOT NULL
status                TEXT NOT NULL  -- open | attention | closed
closed_at_utc         TIMESTAMPTZ NULL
UNIQUE (scope_id, period_start_utc, period_end_utc)
```

O primeiro módulo pode apenas produzir `open`/`attention`/`closed` e relatórios de diferença. Não deve publicar `returns` nem preencher os getters. `closed` exige todos os campos booleanos verdadeiros, zero de `missing_count`/`late_count`, snapshots completos, nenhum intent em estado ambíguo que possa alterar o período, e igualdade `Decimal` por ativo entre saldo inicial + fatos + saldo final. Se for necessário converter ativos para `base_asset`, a conversão exige preço de valuation com origem, timestamp e cobertura igualmente persistidos; sem isso, o fechamento permanece por ativo e não é equity/base-P&L verificado.

## Fluxo de confiança proposto

1. **Adapter autenticado e allowlisted:** somente adapter homologado para o par `venue/environment` obtém saldo, ordens, trades, fees, funding e cashflows diretamente da API/stream correspondente. O módulo não aceita `dict` arbitrário do motor, intent ou caller. Credenciais ficam fora das linhas financeiras.
2. **Normalização:** o adapter cria tipos internos imutáveis com `scope_id` resolvido no servidor, IDs remotos, cursor/sequence, timestamps de fonte UTC e `Decimal`. Resposta sem ID remoto, sem timestamp exigido, com cursor quebrado ou status ambíguo vira `attention`.
3. **Persistência antes de derivação:** fatos são inseridos append-only e idempotentes. O digest do payload bruto é apenas integridade/referência; autenticidade vem da chamada autenticada do adapter, do contrato do endpoint, do cursor e da reconciliação, não do hash.
4. **Reconciliação após restart:** persistir cursor e watermark. Após reinício, reconsultar uma janela sobreposta por ID/cursor e reprocessar idempotentemente. Timeout depois de envio ou depois de resposta não autoriza inferência; a intent fica `recovery_pending` até o venue confirmar. A reconciliação de ordens deve também importar fills tardios, fees e saldos.
5. **Fechamento:** somente o módulo independente escreve `ledger_period_closure_v1.status=closed`. A existência de uma linha audit-only, um `canonical_sha256`, um status `filled`, um snapshot de shape correto ou uma flag booleana do caller nunca é suficiente.
6. **Consumidor futuro:** só depois de aceitação independente um getter read-only poderá consultar closures fechadas do scope exato. Ainda assim, a primeira migração/teste deste incremento deve manter `get_verified_risk_periods()` e `get_verified_trade_returns()` sem retorno verificado, para evitar acoplar autoridade nova ao sizing antes de completar soak e revisão de domínio.

## Critérios binários de completude e aceite

1. **Escopo:** migration cria `ledger_scope_v1` e rejeita duplicidade de `(account_id, venue, environment)`; teste prova que a mesma `source_event_id` em dois environments não colide e não mistura saldos.
2. **Autenticidade de escrita:** não existe endpoint público/genérico para inserir fatos autoritativos; teste tenta fornecer `source`, venue, environment, saldo e hash pelo caller e comprova que o módulo ignora/rejeita esses valores. Apenas adapter homologado consegue emitir o tipo interno.
3. **Imutabilidade:** UPDATE, DELETE, TRUNCATE e conflito de identidade são rejeitados; replay idêntico retorna a mesma linha sem duplicar; replay com qualquer quantia, timestamp, asset ou ID divergente falha sem alterar a primeira linha.
4. **Decimal/UTC:** toda coluna econômica é `NUMERIC(38,18)`; teste rejeita `float`, NaN, infinito, excesso de escala e timestamp sem timezone; round-trip preserva exatamente `0.100000000000000001` em PostgreSQL; saída API converte para string/Decimal, nunca para float.
5. **Fills:** fixture com execução 0,04 + 0,06, fee em moeda distinta, cancelamento e fill tardio produz duas linhas únicas de trade e uma fee; duplicar cada página não altera a soma; status da intent sozinho não cria fill.
6. **Funding/cashflow:** fixture cobre funding positivo e negativo, depósito, saque e transferência com referência externa; evento sem asset, intervalo, tipo ou settlement exigido fica `attention` e não entra em closure.
7. **Saldos/completude:** snapshot com ativo ausente, página incompleta, cursor quebrado, timestamp futuro ou resposta inconclusiva não fecha; snapshot explícito com zero é distinguido de ativo não consultado; coverage manifest só é completo após o watermark final.
8. **Reconciliação exata:** abertura + fatos - fees/funding/cashflows = fechamento por ativo em `Decimal`; qualquer diferença, evento tardio, duplicate conflict ou intent ambígua deixa `status=attention`, com contagem de missing/late, nunca `closed`.
9. **Restart/falha:** testes interrompem o processo antes do envio, depois do aceite remoto, depois do fill e antes do commit local; restart consulta por client ID/cursor, não reenvia de modo cego, não perde nem duplica fatos e mantém bloqueio quando o estado remoto é inconclusivo.
10. **Adapters:** Binance Testnet/Demo só pode ser fonte após fixture read-only de balances/orders/trades/fees/cursors e contrato de ambiente; paper/simulado/FIX stub são rejeitados como autoridade; Forex live/MT5/Mainnet continuam fora até homologação separada. Nenhum teste faz request privado nesta etapa.
11. **Getters/sizing:** mesmo com arrays falsos no `market_context`, `trade_returns_verified=true`, `source=closed_execution_ledger_v1` e snapshot booleano completo, os getters atuais continuam `None` e Kelly não usa esses dados. Nenhum novo teste deve monkeypatchar um getter com dict e chamar isso de prova de autoridade; testes de risco devem distinguir explicitamente fixture de contrato de produção.
12. **Operação:** migration, privilégios separados de writer/migration, retenção, backup/restore e soak de restart em staging são aceites em evidência própria. CI SQLite/pytest não é aceite como prova de exchange ou de restore operacional.

## Blockers para qualquer retorno verificado ou sizing

- Não há produtor autenticado nem scope persistente por conta/venue/environment.
- Não há ledger de execução fechada por trade nem evidência durável de fills parciais, fees multi-moeda, funding e cashflows.
- Não há manifesto de cobertura/cursor nem fechamento independente de saldos por período UTC.
- Quantidades/preços/comissões do caminho de intent/adapter ainda atravessam `Float`; restart não reconstrói fatos econômicos, apenas status da ordem.
- Os getters são corretamente fail-closed; qualquer implementação que consuma autoattestation do caller, `market_context`, hash ou `source` declarativo deve ser rejeitada.

**Conclusão:** o próximo merge autorizado deve ser somente o módulo/migration/testes de ingestão e reconciliação acima, ainda sem dados `verified` para sizing. A decisão permanece **HOLD / live e autonomia fora de autorização** até que cada critério binário tenha evidência reproduzível por scope, venue e environment.

# Follow-up somente leitura — ZT01

**Checkout auditado:** `/home/ubuntu/ZIA-TRADER-v17-phase9-resume`
**Branch:** `fix/zt01-control-plane-and-client-scope`
**Data:** 2026-11-19
**Escopo:** somente os três achados do relatório inicial `zt01_independent_review.md`; nenhum novo subsistema foi auditado.

## Veredito

As **três reproduções materiais do relatório inicial estão fechadas para refinamento com `LIVE` default OFF**:

1. P1-01 — corrida entre o gate Mainnet e o dispatch POST;
2. P1-02 — perda do kill switch após restart;
3. P2 — reutilização de `client_order_id` com payload/conta divergente.

Não encontrei novo P1 específico no escopo desta revisão. **O sistema permanece NÃO ACEITO operacionalmente**, mesmo com os três fechamentos: continuam fora/pendentes os blockers já declarados no relatório inicial, em particular ledger autoritativo, RLS/policies, autenticação JWT persistente, enforcement tenant-aware, validação PostgreSQL/CI e validação em staging. Não houve request para Binance, Testnet ou broker real.

## Reprodução e resultado

### 1. P1-01 — POST após toggle durante await: fechado na fronteira de dispatch da aplicação

A reprodução foi repetida com `FakeSession`/`AsyncMock`, sem rede:

- `test_kill_toggle_inside_to_thread_blocks_legacy_transport`: o toggle para `LIVE_KILL_SWITCH=True` é interposto dentro do caminho `asyncio.to_thread`; o hook em `BinanceSpotAdapter._request_legacy_session()` executa antes de `session.request()`, levanta `MainnetDisabledError` e `session.request` permanece sem chamada.
- `test_async_transport_hook_blocks_toggle_after_signing`: o toggle é interposto após a assinatura e antes do caminho HTTPX; o hook imediatamente anterior a `await self.http_client.request(...)` bloqueia e o request não é aguardado.
- `test_unsigned_mainnet_post_never_reaches_transport`: `POST` com `signed=False` é rejeitado antes da delegação; o transporte não é aguardado.

A implementação correspondente está em `execution/binance_adapter.py:134-190` e `execution/mainnet_adapter.py:55-73`. O `BinanceMainnetAdapter._request()` mantém o gate antecipado, rejeita POST não assinado e o hook final revalida kill/gates, endpoint homologado e `client_order_id` nos caminhos legacy-session e HTTPX.

**Limite do fechamento:** o hook é a última fronteira de dispatch da aplicação. Depois que o request foi despachado, eventual estado remoto desconhecido é irreduzível e deve ser tratado por reconciliação/idempotência. Isto **não** é uma afirmação de zero efeitos entre TCP e processamento no servidor remoto, nem de atomicidade do toggle contra um request que já passou pelo hook.

### 2. P1-02 — kill switch durável após restart: fechado fail-closed

A reprodução foi repetida com SQLite temporário/fake:

- `test_durable_kill_restores_after_database_reopen`: grava `enabled=True`, fecha/reabre `DatabaseManager`, lê o último evento com `LIMIT 1` e `restore_persisted_kill_state()` força `LIVE_KILL_SWITCH=True`.
- `test_missing_or_failed_kill_read_never_rearms_live`: getter ausente, getter que falha e último evento inválido/`enabled=False` mantêm o bloqueio quando a configuração é de autorização live; a mensagem privada da exceção não é propagada.
- `test_kill_is_local_and_durable_before_remote_await`: `TradingManager.trigger_kill_switch()` grava latch local e evento persistido antes de aguardar o cancelamento remoto; o callback observa ambos já ativos.
- `test_failed_kill_write_stays_locally_blocked_without_remote_request`: falha da persistência mantém `LIVE_KILL_SWITCH=True`, não chama o remoto e devolve erro sanitizado.

A restauração é chamada em `core/manager.py:34-40`, antes de `ExchangeConnector(settings)`. A leitura está em `database_manager.py:1255-1263`, filtrada por conta, ordenada por timestamp/ID e limitada a uma linha. O restaurador está em `execution/live_authorization.py:85-102`: ausência, leitura falha, estado inválido ou evento ativo fecham; um evento falso não constitui rearm automático em configuração live. Não foi criada nem considerada necessária uma operação de rearm habilitadora nesta rodada.

O default efetivo, com as variáveis LIVE removidas do ambiente, foi confirmado como:

```text
LIVE_TRADING_ENABLED=False
LIVE_MODE=False
LIVE_KILL_SWITCH=True
SHADOW_MODE_ENABLED=True
BINANCE_MODE=simulated
```

### 3. P2 — `client_order_id` divergente: fechado como conflito explícito sem envio

A reprodução foi repetida em SQLite temporário:

1. reservar `client-reused` para `account-a`, `BTC/USDT`, `buy`, quantidade `1`, preço `100`;
2. marcar a intent como `filled`;
3. tentar `account-b` com o mesmo ID e payload: `IntentIdempotencyConflict`;
4. tentar no reconciliador `ETH/USDT`, `sell`, quantidade `999`, preço `200`: retorno `status == "idempotency_conflict"`, sem campo `intent`, sem chamada ao sender;
5. a intent original permanece BTC e a repetição do payload original continua `filled`.

A identidade canônica em `infra/intent_identity.py:10-33` valida conta, símbolo, ação, tipo, quantidade e preço, normalizando números por `Decimal` sem tolerância oculta. `DatabaseManager.reserve_order_intent()` (`database_manager.py:1118-1148`) compara também após reload em caso de `IntegrityError`, fechando a corrida de inserção. `OrderReconciler.submit_with_retry()` (`core/reconciliation.py:160-171`) converte a divergência em conflito dedicado antes de qualquer recuperação/reuso ou envio.

## Testes executados

Com o virtualenv local, root no `PYTHONPATH`, sem rede, sem cache do pytest e sem bytecode persistente:

```text
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider tests/test_zt01_review_regressions.py
8 passed, 1 warning in 4.69s
```

Os oito testes coletados foram exatamente os listados acima. O `git status` final mostrou somente as alterações/arquivos que já estavam presentes no checkout antes desta revisão; não houve edição, commit, push, ativação de flag, seleção de serviço live ou acesso de rede de trading durante o follow-up.

## Conclusão

Os três casos originalmente reproduzidos estão corrigidos no escopo declarado e podem seguir para refinamento sob `LIVE` default OFF. Isto não altera o veredito operacional: **NÃO ACEITO** enquanto permanecerem os blockers de ledger autoritativo, RLS/isolation enforcement, autenticação multiusuário durável, integração tenant-aware e validação PostgreSQL/staging. O fechamento do hook também deve ser interpretado somente como controle de dispatch da aplicação, com reconciliação obrigatória quando o resultado remoto ficar desconhecido.

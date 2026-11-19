# Parecer independente — ZT01 client scope e control plane

**Checkout auditado:** `/home/ubuntu/ZIA-TRADER-v17-phase9-resume`
**Branch:** `fix/zt01-control-plane-and-client-scope`
**Base informada:** `base10168db`
**Data da revisão:** 2026-11-19
**Modo:** somente leitura; nenhum arquivo do repositório foi alterado, nenhum commit/push foi feito, nenhuma flag foi ativada e nenhuma rede de trading foi acessada.

## Veredito

**NÃO ACEITAR para aceite operacional do control plane/mainnet nesta forma.** Foram encontrados dois blockers P1 no ciclo de vida do kill switch e uma inconsistência P2 de reutilização de `client_order_id`. A fundação de client scope e os gates de entrada avaliados são, em geral, fail-closed, mas isso não compensa a possibilidade de um POST passar por uma janela de corrida após o kill toggle nem a perda do kill state em restart.

O documento de progresso mantém a métrica declarada de **16 gates, 7 PASS**; este parecer não recalcula nem propõe percentual novo. Essa métrica não é autorização de live trading.

## Achados materiais

### P1-01 — POST mainnet pode ser transmitido depois de o kill switch ser ativado durante um await

**Arquivos/linhas:**

- `execution/mainnet_adapter.py:55-63`: o adapter revalida o gate, mas depois entrega o controle ao transporte com `await super()._request(...)`.
- `execution/binance_adapter.py:162-176`: quando há uma `session`, o transporte aguarda `asyncio.to_thread(...)`; o `session.request(...)` efetivo ocorre em `:151-160` sem nova verificação do kill state.

**Reprodução somente com mock:** usei `BinanceMainnetAdapter` construído com `FakeSession`, credenciais fictícias e `asyncio.to_thread` interposto para executar `settings.LIVE_KILL_SWITCH = True` antes de chamar a função transportadora. A chamada foi:

```python
await adapter._request(
    "POST", "/v3/order",
    {"newClientOrderId": "mock-intent"},
    signed=True,
)
```

Resultado observado: `result == {"ok": True}`, `calls == 1` e `LIVE_KILL_SWITCH == True`. Ou seja, o POST mock foi efetivamente entregue depois do toggle. Nenhuma exchange foi acessada.

**Impacto:** em produção, uma ordem de entrada/proteção poderia cruzar o kill switch se o toggle ocorrer entre o check no adapter e a execução do transporte. O check adicional após normalização cobre um await anterior conhecido, mas não cobre esta janela transportadora.

**Patch exato proposto, sem aplicar:**

1. Adicionar em `BinanceSpotAdapter` um hook síncrono no ponto imediatamente anterior ao transporte:

```python
def _before_transport_request(
    self,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]],
) -> None:
    return None
```

2. Chamar esse hook imediatamente antes de `self.session.request(...)` em `execution/binance_adapter.py:151` e imediatamente antes de `await self.http_client.request(...)` em `:176`:

```python
if method.upper() == "POST":
    self._before_transport_request(method, path, params)
response = self.session.request(...)
```

```python
if method.upper() == "POST":
    self._before_transport_request(method, path, params)
response = await self.http_client.request(...)
```

3. Sobrescrever no mainnet adapter, mantendo o check antecipado existente:

```python
def _before_transport_request(
    self,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]],
) -> None:
    if method.upper() == "POST":
        self._assert_live_write()
```

4. Como defesa adicional do contrato interno, `BinanceMainnetAdapter._request` deve rejeitar `POST` com `signed=False` antes de delegar ao adapter base. O teste de regressão deve afirmar que, após o toggle interposto imediatamente antes do transporte, ocorre `MainnetDisabledError` e `FakeSession.calls == []` nos caminhos `session` e `httpx` mockado.

### P1-02 — ativação do kill switch não é restaurada de modo durável após restart

**Arquivos/linhas:**

- `core/manager.py:123-130`: `trigger_kill_switch` grava `settings.LIVE_KILL_SWITCH = True`, atualiza a métrica e chama `record_kill_switch(...)`.
- `database_manager.py:1236` (método de registro): o evento é persistido, mas não há leitura correspondente no startup.
- `execution/live_authorization.py:37-52`: `live_submission_block_reason` decide pelo objeto `settings` corrente.
- `config/startup_validation.py:79-82`: valida autostart/live, mas não carrega o último `KillSwitchEvent` antes da seleção do adapter.
- `core/manager.py:54-55`: o `ExchangeConnector` é criado sem restaurar o estado persistido.

**Reprodução sem rede:** considerando `LIVE_TRADING_ENABLED=true`, `LIVE_MODE=true`, `SHADOW_MODE_ENABLED=false`, `BINANCE_MODE=live`, `MANUAL_TRADING_ENABLED=true` e `LIVE_KILL_SWITCH=false` no ambiente, um `POST /admin/kill-switch` ativa o estado apenas no processo corrente e grava o evento. Após restart com as mesmas variáveis, o objeto de configuração volta a `LIVE_KILL_SWITCH=false`. O status calculado em mock foi:

```text
{'live_kill_switch': False, 'live_flags_passed': True, 'block_reason': None}
```

Não há leitura de `KillSwitchEvent` que converta o último evento ativo em bloqueio antes de permitir nova ordem. `AUTO_START_ENGINES=false` impede o autostart, mas não transforma o estado persistido do kill em uma trava de processo; um start manual posterior continua sendo uma superfície a considerar.

**Impacto:** a ação operacional de emergência não sobrevive a restart. Em uma configuração de desenvolvimento/controlled deployment que permita live, o processo reiniciado pode voltar a aceitar POST mesmo que o último estado operacional persistido seja kill ativo.

**Patch exato proposto, sem aplicar:**

1. Adicionar ao `DatabaseManager` uma leitura limitada e determinística do último evento para a conta:

```python
def get_latest_kill_switch(self, account_id: str) -> dict | None:
    with self.SessionLocal() as db:
        row = (
            db.query(KillSwitchEvent)
            .filter(KillSwitchEvent.account_id == account_id)
            .order_by(KillSwitchEvent.timestamp.desc(), KillSwitchEvent.id.desc())
            .first()
        )
        if row is None:
            return None
        return {"enabled": bool(row.enabled), "reason": row.reason, "actor": row.actor}
```

2. Em `TradingManager.__init__`, depois de `runtime_registry.apply_to_settings(settings)` e **antes** de `ExchangeConnector(settings)`, ler esse estado. Se a leitura falhar, manter/forçar `LIVE_KILL_SWITCH=True` e abortar qualquer seleção live; se o último evento for `enabled=true`, forçar `settings.LIVE_KILL_SWITCH=True` e `KILL_SWITCH_ACTIVE.set(1)`.

3. Criar uma operação de rearm explícita e durável que grave `enabled=false`, com autorização administrativa adicional e auditoria. Sem esse evento durável, um restart deve permanecer bloqueado. Adicionar testes: kill, dispose/recriação do manager, último evento ativo ainda bloqueia; leitura indisponível fail-closes; somente rearm persistido libera o estado. Não usar apenas o valor carregado do `.env` como restauração.

### P2 — `client_order_id` já preenchido pode ser reutilizado para payload diferente sem conflito explícito

**Arquivos/linhas:**

- `api/routers/operations.py:74-91`: a rota manual aceita `client_order_id` enviado pelo chamador.
- `core/reconciliation.py:53-56`: `reserve()` retorna a intent existente sem comparar símbolo, ação, tipo, quantidade, preço ou conta.
- `core/reconciliation.py:167-189`: a intent existente é consultada e, se está `filled`, retorna `idempotent_reuse`; se está aberta, reconcilia usando os dados persistidos da intent antiga.
- `database_manager.py:1116-1138`: `reserve_order_intent()` busca por `client_order_id` global e devolve a linha existente sem rejeitar divergência de payload.

**Reprodução com SQLite temporário e mock:**

1. Reservar `client-reused` para `BTC/USDT buy 1.0 @ 100` e marcá-lo `filled`.
2. Submeter `ETH/USDT sell 999 @ 200` com o mesmo `client_order_id`.
3. Resultado observado no `ExecutionEngine`: `status == "idempotent_reuse"`, `adapter_calls == 0`, e a intent armazenada continua sendo a ordem BTC antiga.

Isso é fail-closed quanto ao envio (não houve duplicação), mas não é uma rejeição explícita de conflito: o chamador recebe o resultado de uma intent de outro payload e a semântica fica perigosa para qualquer consumidor que interprete `idempotent_reuse` como aceitação da nova solicitação. A colisão também não verifica `account_id` antes de devolver a intent global.

**Patch exato proposto, sem aplicar:**

1. Em `OrderReconciler`, adicionar comparação canônica de identidade da intent (`account_id`, símbolo normalizado, ação, `order_type`, quantidade e preço com tolerância definida).
2. Depois de `reserve()` e **antes** de qualquer ramo de recuperação/reuso, comparar a intent existente com a solicitação. Se houver divergência, retornar um status dedicado (`idempotency_conflict`) ou lançar `ReconciliationError`; nunca consultar/reutilizar a ordem antiga para o novo payload:

```python
existing = self.db_manager.get_order_intent(client_id) or await self._cached_intent(client_id)
if existing is not None and not self._same_intent(prepared, existing):
    return {
        "status": "idempotency_conflict",
        "client_order_id": client_id,
        "reason": "client_order_id já reservado para payload/conta diferente",
        "intent": existing,
    }
```

3. Fazer `reserve_order_intent()` rejeitar explicitamente conta ou payload divergentes e cobrir isso com fixture de ordem preenchida e segunda solicitação em símbolo/ação/quantidade diferentes. Este achado é residual da camada de idempotência anterior, não uma regressão introduzida pela migration de client scope, mas é material para o contrato de IDs.

## Verificações que passaram

- **Raw credentials:** não encontrei emissão de API key, secret, senha ou token em `BrokerAccountV1`, no escopo resolvido, no catálogo/status ou nos logs novos. O schema de `broker_account_v1` guarda somente `account_ref` opaco e identidade de venue/ambiente; não guarda credenciais.
- **Tenant B versus membership A:** `resolve_client_scope()` exige caller confiável, tenant/account explícitos, principal ativo, membership ativa no tenant solicitado, account ativa pertencente ao mesmo tenant e role suficiente. A consulta não permite usar a membership de A para resolver a conta de B. Isso foi coberto pela suíte de SQLite; o teste PostgreSQL não executou localmente por falta de `TEST_DATABASE_URL`.
- **Status versus autorização:** `/core/analyze` retorna `execution_authorized: false`; `health_payload` expõe flags solicitadas e `live_flags_passed` como diagnóstico. A rota legada de ordem continua entrando pelo `OrderManager`, que aplica fonte, modo, confirmação, risco, reconciliação e autorização. Não tratei `execution_gate_status` como prova de autorização de ordem.
- **Dynamic autonomy/Redis:** `RoboTraderUnified`, `SniperEngine` e `OrderManager` reavaliam Redis no call boundary para novas entradas. A confirmação AI preserva `signal_validated` e revalida os gates. O gate Redis é de entrada; `submit_exit()` não chama esse veto dinâmico, preservando saídas quanto à perda de persistência Redis. Contudo, em Mainnet o kill switch global bloqueia o POST de saída também, pois o mesmo transporte é usado para entrada e saída; se o requisito operacional for permitir fechamento de emergência durante kill, será necessário um caminho de redução separado e explicitamente auditado.
- **Exits:** o teste existente de entrada/saída centralizada passa; o teste de risco confirma que falha de Kelly/ledger não bloqueia `validate_exit()`. Isso não equivale a autorização de live.
- **Regime/data guard:** `MarketRegimeDetector` rejeita DataFrame ausente, OHLC não finito, preços inválidos e `high < low`; o `TrendAlignmentFilter` bloqueia `regime=unknown`. O comando offline fecha notícias/entrada e declara `execution_authorized=false`; não encontrei envio nesse caminho.
- **Mainnet POST/protection/OCO:** `place_order`, `place_protection_order`, `MarketConnector.place_order`, `place_protection_order` e `place_oco_orders` passam por gates novos/locais; `client_order_id` é exigido no adapter Mainnet para order/protection. O achado P1-01 demonstra que o check não é atômico no instante do transporte. O adapter Mainnet atual não implementa OCO nativo; o caminho OCO cai em ordens separadas/unsupported conforme adapter, portanto não considerei haver uma prova de atomicidade OCO.
- **Migration:** a migration `c3f1e2a9b7d4` é aditiva, recusa as quatro tabelas preexistentes, recusa downgrade parcial ou com dados, remove filhos antes dos pais e não contém credenciais/RLS/ledger. Os testes SQLite cobrem upgrade idempotente, guard de tabela preexistente e downgrade com dados. Os testes PostgreSQL foram pulados por ausência de `TEST_DATABASE_URL`; não há claim de round-trip PostgreSQL nesta máquina.

## Blockers de escopo, explicitamente fora de achados da fundação

1. A migration e `core/client_scope.py` são somente uma fundação. **Não há RLS**, políticas de banco, enforcement tenant-aware nas APIs legadas ou troca da conta fixa `default_account` pelo scope resolvido.
2. **Não há JWT persistente/multiusuário durável** integrado ao client scope. `TrustedCaller` não autentica ninguém; ele só aceita issuer/subject já verificados pelo chamador. Não tratar `TrustedCaller` como autenticação.
3. As APIs legadas continuam single-account. Nenhuma rota em `api/routers/` chama `resolve_client_scope`; isso é compatível com o escopo declarado desta etapa, mas bloqueia qualquer claim de SaaS multi-tenant.
4. O ledger autoritativo de execução/fill/fee/funding permanece ausente; o ledger audit-only não vira fonte autoritativa de risco ou equity nesta rodada.
5. O `alembic check` local terminou com `Target database is not up to date` (exit 255) porque o banco local de trabalho não está no head; não foi alterado para fabricar um resultado verde. A validação PostgreSQL real requer ambiente separado/CI com `TEST_DATABASE_URL`.
6. Não houve request Mainnet, Testnet ou broker real. Todas as reproduções deste parecer usaram FakeSession, mocks, SQLite temporário e o virtualenv local.

## Testes executados nesta revisão

- `pytest -q tests/test_client_scope.py tests/test_database_migrations.py tests/test_postgres_client_scope.py tests/test_dynamic_autonomy_gates.py tests/test_control_plane_safety.py`: **40 passed, 2 skipped, 1 warning**. Os dois skips dependem de PostgreSQL externo.
- Regressão direcionada de reconciliação/IDs, persistência e adapter Mainnet: **42 passed, 1 warning**.
- `git diff --check`: sem saída de erro.

**Conclusão:** corrigir P1-01 e P1-02 antes de qualquer aceite do control plane. Corrigir P2-03 antes de declarar o contrato de idempotência/supersessão completo. Mesmo após esses patches, RLS, JWT persistente, integração tenant-aware, ledger autoritativo e validação PostgreSQL/staging continuam blockers declarados e não são resolvidos por esta fundação.

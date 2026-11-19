# Auditoria read-only — isolamento por cliente e identidade

**ID:** `tenant-isolation`
**Checkout auditado:** `/home/ubuntu/ZIA-TRADER-v17-phase9-resume`
**Base verificada:** `09ea8c8` (PR33 head09ea8c8)
**Escopo:** autenticação JWT/current_user, RBAC, configurações globais e modelos/caminhos de conta, intents, ledger e dados privados.
**Método:** inspeção estática read-only, sem navegador, sem execução do servidor, sem acesso a banco persistente, sem leitura/exibição de `.env`, chaves ou credenciais. O checkout estava limpo no início da inspeção; o único artefato criado foi este relatório fora do checkout.

## Conclusão executiva

**Não existe isolamento por tenant.** O que existe é autenticação configurada por ambiente/processo e uma convenção de `account_id` em parte das tabelas. O JWT autenticado identifica, na prática, um `sub` que é procurado contra usuários configurados no `Settings`; o RBAC decide apenas se o papel global contém `admin` ou `trader`. O runtime criado pela aplicação usa uma única conta fixa, `default_account`, para execução, status, logs e reconciliação.

A presença de `account_id` em `account_state`, posições, PnL, histórico, intents, proteção, reconciliação, kill switch e ledger é útil como particionamento legado, mas não é uma fronteira de segurança: não há entidade tenant, associação persistente principal–tenant–conta, vínculo conta–venue–environment, foreign keys de escopo, contexto server-side obrigatório, restrição uniforme em todas as queries ou RLS. Dados públicos de mercado podem continuar compartilhados; isso não torna os dados financeiros e configurações privadas isolados.

O guia de sandbox já registra corretamente que identidade persistente por cliente e isolamento por tenant estão pendentes. O estado atual de live/autonomia/manual/autostart OFF reduz risco operacional desta rodada, mas não transforma a arquitetura em multiusuário.

## Achados materiais

### 1. P0 — identidade é por configuração de ambiente, não uma identidade persistente multi-tenant

**Evidência:** `api/dependencies.py:36-65` monta `auth_users()` a partir de `Settings.AUTH_*` ou usuários demo; em `AUTH_MODE=env` há um único usuário configurado e papéis fixos `admin`/`trader`. `api/routers/auth.py:41-46` emite JWT contendo essencialmente `sub`; `security/jwt_utils.py:45-53` valida assinatura/algoritmo e a presença de `sub`, mas não resolve membership persistente, tenant, conta, venue ou environment. `cli/db_models.py:15-28` possui `admin_users`, porém essa tabela não é a fonte usada por `get_current_user()`.

**Impacto:** dois usuários/tenants não têm identidade e autorização de objeto persistentes no caminho HTTP. Não há revogação/estado ativo consultado, membership, papel por tenant/conta ou separação de credencial por cliente. Um claim `tenant_id` adicionado ao JWT no futuro não seria suficiente e não deve ser aceito sem validação contra membership persistente. `rbac_utils.py:3-13` faz apenas presença de role; `security/rbac_manager.py` também define permissões globais, sem escopo de objeto.

**Critério de encerramento:** um `sub` validado deve apontar para um principal persistente; cada acesso deve resolver membership e papel no banco. Token sem membership ativa, ou com seleção de conta não pertencente ao principal, deve falhar com `403`; nenhum tenant/account vindo apenas do corpo ou de claim não verificado pode alterar o escopo.

### 2. P0 — a API e o runtime compartilham uma conta e um estado operacional global

**Evidência:** `api/routers/operations.py:47-52` lê `default_account` em `/status`; `:118-119` usa a mesma conta em `/logs`; `/order` e `/order/confirm` aceitam o papel, mas não recebem um escopo de conta do servidor. `core/manager.py:60-66` instancia `ExecutionEngine(..., account_id="default_account")`; `execution/execution_engine.py:29-35`, `core/engine.py:58-59` e `core/sniper_engine.py:41` mantêm o mesmo default. O WebSocket em `api/routers/engines.py:35-49` transmite `runtime_status_payload` global, sem principal/conta.

**Impacto:** qualquer trader autenticado no mesmo processo opera/consulta a mesma conta lógica e o mesmo runtime. O kill switch administrativo também grava o account do reconciler compartilhado (`core/manager.py:115-121`). Não há como distinguir “usuário A da conta A” de “usuário B da conta B” no caminho atual. Adicionar `tenant_id` ou `account_id` livre no JSON seria uma regressão: o cliente escolheria o objeto que o servidor deve autorizar.

**Critério de encerramento:** a rota deve receber apenas um seletor não autoritativo (ou usar a conta padrão do membership) e o servidor deve injetar um `Scope` resolvido; `TradingManager`, `ExecutionEngine`, WebSocket, status, logs, intents e kill switch não podem depender de `default_account` em caminho multi-tenant. Sem scope, o caminho deve falhar fechado, não cair em default.

### 3. P0 — o schema não modela a fronteira tenant–account–venue–environment

**Evidência:** `database.py:44-50` define `AccountState.account_id` como string única, sem `tenant_id`, venue, environment ou foreign key. As demais entidades financeiras usam `account_id` livre; o ledger (`database.py:151-199`) também tem apenas `account_id`. A migração inicial confirma a mesma forma em `migrations/versions/8d429f0ec081_initial_versioned_schema.py:35-60`, `:152-160`, `:232-248`, `:345-386` e `:403-438`. `cli/db_models.py:30-42` registra `exchange_configs` com `account_name`, sem tenant/conta persistente/venue/environment; `strategy_configs` e `algorithm_configs` são globais.

Há ainda tabelas que podem conter dados privados de uma execução, decisão ou backtest — por exemplo `ai_observations`, `market_patterns`, `backtest_runs`, `decision_snapshots`, `trades` e metadados JSON — sem coluna de propriedade. Candles, notícias e tendências podem ser deliberadamente compartilhados como dados de mercado/contexto; essa decisão precisa ser explícita e não pode ser estendida por acidente a saldo, ordens, fills, credenciais, logs ou decisões de um cliente.

**Impacto:** `account_id` identifica uma partição nominal, não uma relação autorizada. Não há integridade que impeça a mesma string de ser usada por tenants distintos, nem vínculo que permita ao banco verificar que uma linha pertence à conta/venue/environment corretos.

**Critério de encerramento:** criar entidades e foreign keys para tenant, principal, account e vínculo account–venue–environment; as tabelas do piloto devem usar chaves e constraints não nulas. Tabelas fora do piloto permanecem fora da API privada, em vez de receber uma migração em massa sem classificação de dados.

### 4. P0 — o repositório não impõe scope server-side de forma uniforme; vários identificadores cruzam contas

**Evidência:** vários métodos filtram `account_id` somente quando o chamador o fornece (`database_manager.py:145-163`, `:189-204`, `:264-315`, `:505-520`). Isso é uma convenção de chamada, não uma política. `get_system_logs()` devolve todos os logs quando o argumento é omitido (`database_manager.py:1071-1077`). `update_position()` (`:175-187`) e `update_order_status()` (`:1029-1037`) localizam por ID global. Mais importante, `reserve_order_intent()` procura somente por `client_order_id` e retorna a intenção existente (`:1116-1138`); `get_order_intent()`/`update_order_intent()` fazem o mesmo (`:1142-1164`). `upsert_protection_order()` e `update_protection_order()` também localizam por `client_order_id` sem a conta (`:1194-1234`). Esses campos são globalmente únicos no schema, não uma autorização de pertencimento.

**Impacto:** um worker, endpoint futuro ou recuperação que possua um ID de outra conta pode ler ou atualizar uma linha de outro cliente. A captura/listagem de ledger (`:336-350`, `:505-520`) valida formato e filtra pelo `account_id` recebido, mas aceita esse identificador livre; não existe contexto de tenant/venue/environment que o servidor ou o banco possam confrontar. A superfície atual não expõe todos esses métodos diretamente, porém o contrato interno já não oferece defesa contra uma futura rota de leitura por ID.

**Critério de encerramento:** toda leitura, update, delete, upsert e `INSERT ... ON CONFLICT` de dado privado deve receber um `Scope` server-side obrigatório e incluir a restrição explícita da tupla de escopo no SQL. Um lookup por `client_order_id`, ID numérico ou `source_event_id` sem a restrição do scope deve ser impossível no repositório; chamada sem scope deve falhar com erro determinístico. A unicidade de intents/proteções deve ser composta pelo scope quando o modelo for promovido.

### 5. P1 — o ledger é um bom piloto de append-only, mas ainda não é uma fronteira privada nem tem RLS

**Evidência positiva:** `equity_ledger_v1` é documentado como audit-only, valida tipos/quantidade/tempo, calcula hash canônico, possui idempotência por origem e triggers de imutabilidade na migração `a5c74e8d2b91_equity_ledger_v1_audit_only.py`. A listagem é limitada e paginada (`database_manager.py:505-520`). Isso deve ser preservado.

**Lacuna:** a mesma tabela só conhece `account_id` textual; `append_equity_ledger_event()` recebe esse valor do chamador e não conhece tenant, venue ou environment. Não há política PostgreSQL RLS, `FORCE ROW LEVEL SECURITY`, contexto transacional `SET LOCAL` ou `WITH CHECK` que impeça um papel de banco/app de inserir ou consultar outra conta. `account_state` tem a mesma lacuna. Portanto, “ledger audit-only” significa não ser fonte autoritativa de equity/risk; não significa isolamento entre clientes.

**Critério de encerramento:** o piloto só pode considerar uma linha privada válida quando o scope completo for resolvido server-side, persistido com foreign keys e verificado por SQL explícito; em PostgreSQL, a política RLS do piloto deve negar `SELECT/INSERT/UPDATE/DELETE` cross-tenant inclusive em teste com acesso direto ao banco. Não backfillar linhas legadas de `default_account` sem proveniência inequívoca.

## Fundação aditiva proposta

### 1. Control plane de identidade e escopo

Adicionar, sem alterar ainda todas as tabelas existentes:

- `tenants`: identificador UUID, estado e timestamps.
- `principals`: identificador UUID, `auth_subject` único (o `sub` validado), estado de acesso e timestamps. O segredo não fica nessa tabela.
- `tenant_memberships`: `(tenant_id, principal_id, role, status)` com unicidade composta e auditoria de concessão/revogação.
- `accounts`: `(tenant_id, account_id UUID, name, status)`; o ID legado textual não deve ser tratado como prova de ownership.
- `account_venues`: ligação da conta a venue e `environment` (`sandbox`, `testnet`, `live`), com `credential_ref` opaco; segredos permanecem fora de payloads e não são duplicados no escopo.

O servidor constrói um objeto imutável equivalente a:

```text
Scope {
  principal_id,
  tenant_id,
  account_id,
  venue_id,
  environment,
  role
}
```

O `Scope` nasce de JWT validado + lookup de principal/membership + seleção autorizada de conta. O corpo pode selecionar um identificador de conta para uma rota futura, mas não pode declarar `tenant_id`, papel, venue ou environment como autoridade. Se um JWT carregar esses claims, eles devem ser ignorados para autorização ou confrontados com membership persistente; nunca aceitos isoladamente.

### 2. Restrição explícita em SQL e preparação para RLS

Cada repository privado deve receber `Scope`, não uma string solta. Reads e writes devem conter predicados explícitos para tenant, account, venue e environment, ou para um `scope_id` que tenha foreign keys e seja resolvido a partir dessa tupla. Inserts devem preencher esses campos exclusivamente do `Scope`; IDs do corpo entram apenas como dados e são validados contra a linha já escopada. `UPDATE`, `DELETE`, `UPSERT` e recuperação de intent devem combinar o identificador de negócio com o scope.

No PostgreSQL do staging, o piloto deve definir `app.tenant_id`, `app.account_id`, `app.venue_id` e `app.environment` com `SET LOCAL` dentro da transação, a partir do `Scope` server-side, e aplicar `USING`/`WITH CHECK` nas tabelas-piloto. A aplicação não deve confiar em `current_setting` que o cliente possa controlar. RLS é defesa adicional, não substitui os predicados explícitos nem o membership check. SQLite do sandbox não simula RLS; seus testes devem verificar o mesmo contrato no repository e reservar o teste de política para PostgreSQL efêmero/staging.

### 3. Piloto seguro: somente conta privada + ledger audit-only

Escolher apenas `account_state` e uma nova tabela irmã do ledger, por exemplo `equity_ledger_scoped_v1`, ligada a uma linha de escopo control-plane. Não migrar cegamente `trades`, observações, snapshots, backtests, candles, notícias, configs globais, intents ou todo o histórico.

O piloto deve:

1. Criar os registros de tenant/principal/membership/account/venue-environment em dados sintéticos de sandbox/testnet.
2. Persistir saldo privado e evidência audit-only em tabelas novas ou em uma versão nova com colunas de escopo `NOT NULL`, foreign keys, unicidade composta e triggers append-only mantidos.
3. Expor somente um repository de leitura/inserção de saldo/ledger que exija `Scope`; nenhuma rota deve usar `default_account` nesse caminho.
4. Manter o ledger como evidência, não como fonte de sizing, risco, equity autoritativa ou autorização de trading.
5. Não reclassificar registros antigos: a linha legada só será associada a um tenant após mapeamento aprovado e evidência de origem; caso contrário permanece fora da visão privada.
6. Exigir `environment != live` no piloto por constraint e gate server-side. Nenhum toggle de live, autonomia, manual ou autostart deve ser alterado por esta fundação.

Intents e proteções ficam como segunda etapa. Antes disso, suas operações por `client_order_id` devem ser encapsuladas para não serem reutilizadas por uma API multi-tenant; quando promovidas, usar unicidade composta por escopo e testar a colisão entre contas.

## Testes cross-tenant e limites verificáveis

Os testes devem usar dois tenants sintéticos (`tenant-a`/`tenant-b`), dois principals, duas contas e pelo menos duas combinações venue/environment; não usar credenciais reais.

1. **Membership:** principal A com membership somente em A recebe `200` apenas para o scope de A e `403` para seleção de B; principal sem membership recebe `403`. Um papel `admin` de A não é admin de B por herdar o nome da role.
2. **Corpo adulterado:** enviar `tenant_id`, `account_id`, `venue_id` e `environment` de B no corpo de uma requisição autenticada como A deve ser rejeitado ou ignorado, mas nunca mudar o `Scope`; a resposta e a linha criada continuam em A.
3. **Claim adulterado:** token assinado para principal A com claim `tenant_id=B` não concede B. O servidor resolve membership persistente e retorna `403` ou rejeita o token por claims inconsistentes.
4. **Leitura de saldo/ledger:** inserir saldo e eventos distintos em A e B; listar/consultar como A nunca retorna IDs, valores, eventos, hashes ou contagens de B. A tentativa direta de consultar B por `account_id` textual deve retornar `403`/vazio conforme o contrato, sem fallback para `default_account`.
5. **Escrita de ledger:** A não pode inserir evento com combinação de tenant/account/venue/environment de B; o service deve falhar antes do commit e o PostgreSQL `WITH CHECK` deve falhar mesmo se a chamada SQL for tentada com o papel da aplicação.
6. **Scope ausente:** chamar qualquer método privado sem `Scope` deve falhar de forma determinística; não pode retornar dados globais, escolher `default_account` ou aceitar `tenant_id` fornecido pelo cliente.
7. **Venue/environment:** A em `testnet` não pode ler/escrever a linha `live` da mesma conta, nem usar a linha de outra venue. O piloto deve rejeitar `live` por constraint/gate, mesmo com role `admin` comum.
8. **Identificador de negócio para a próxima etapa:** preparar teste em que A e B usam o mesmo `client_order_id`; nenhum `get/update` de A pode alcançar B. Se intents ainda não forem migradas, a chamada multi-tenant deve permanecer bloqueada, não ser “corrigida” por aceitar o ID global.
9. **RLS direto:** com uma conexão PostgreSQL de aplicação configurada para A, `SELECT`, `INSERT`, `UPDATE` e `DELETE` no piloto devem ser incapazes de atravessar para B; testar também `FORCE ROW LEVEL SECURITY` e ausência de bypass pelo owner do app.
10. **Auditoria:** ações de leitura/escrita privada registram principal, tenant, account, venue, environment, ação e resultado sem token, senha ou chave; a ausência de escopo ou tentativa cross-tenant é auditável como negativa.

### Critérios de aceite do piloto

- [ ] Existe membership persistente e o `sub` JWT resolve um único principal; nenhum tenant é autorizado somente por claim/body.
- [ ] O piloto não contém fallback para `default_account` e falha fechado quando o `Scope` está ausente.
- [ ] Todas as queries do repository de `account_state`/ledger incluem a restrição explícita do scope; isso é coberto por testes de leitura, insert e update.
- [ ] Duas bases sintéticas A/B passam os dez testes acima sem vazamento, alteração ou contagem cruzada.
- [ ] PostgreSQL do piloto tem RLS `USING` e `WITH CHECK`, `FORCE ROW LEVEL SECURITY`, e o teste direto de banco nega as quatro operações cross-tenant.
- [ ] O ledger continua append-only, idempotente, audit-only e sem backfill ambíguo.
- [ ] `live`, execução autônoma, autostart e credenciais reais continuam fora do piloto e desabilitados; não há ordem enviada.
- [ ] Somente depois desses critérios o padrão pode ser replicado para intents/proteções e, em seguida, para outras tabelas classificadas; não há aceite por percentual genérico.

## Limites e conclusão

Esta auditoria não certifica autorização de produção, RLS em banco real, recuperação/revogação completa de credenciais ou isolamento de todas as tabelas. Também não recomenda tornar cada dado de mercado tenant-scoped sem antes classificá-lo; feeds públicos podem permanecer compartilhados, enquanto dados privados e configurações devem ser explicitamente escopados. O próximo incremento seguro é o control plane + piloto privado de `account_state`/ledger audit-only, com SQL explícito e RLS testada; a migração abrangente só deve ocorrer após cada família de dados ter proprietário, finalidade e contrato de retenção definidos.

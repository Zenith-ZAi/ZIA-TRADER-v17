# Fase 9.3 — Auditoria de persistência síncrona em corrotinas

**Data:** 2026-10-23 (local; PR #24 integrado em 2026-10-24 UTC). **Base:** `master` pós-PR #24, `eeee740158e3bee052a27983aef7d6fcd04d8f38`. **Estado:** inventário estático inicial concluído; nenhuma migração de persistência foi aplicada. **Escopo:** mapear I/O SQL síncrono chamado por corrotinas do backend, identificar limites de `Session` e priorizar um rollout sem alterar gates, ordens ou estratégia.

## 1. Resumo executivo

A API e os motores expõem corrotinas, mas a camada atual `DatabaseManager` é síncrona (`create_engine`, `sessionmaker`, `Session.query`, `commit`, `refresh`). O problema predominante não é uma `Session` explicitamente compartilhada entre tarefas: os métodos examinados criam uma Session local e a fecham dentro do helper. O problema comprovado é que corrotinas chamam esses helpers sincronamente, no mesmo thread do event loop.

Uma varredura AST direcionada identificou **59 chamadas** a métodos do `DatabaseManager` com operações ORM, distribuídas por **24 funções assíncronas em 15 arquivos** (contagem indicativa e inferior: não inclui wrappers como `RiskAI`, `PatternMemory`, `health_payload` e outras cadeias indiretas sem `db_manager` explícito no call site). As maiores concentrações aparecem no loop principal (`core/engine.py`), reconciliação/idempotência (`core/reconciliation.py`), Sniper (`core/sniper_engine.py`) e OCO (`execution/oco_manager.py`). A inspeção independente encontrou ainda I/O SQL síncrono em health checks, reload de configuração e startup do worker.

O caminho de ordem contém leituras e transições de intent síncronas antes/depois de awaits de rede; persistência de posições/proteções também é síncrona após o fill ou chamada do adapter. Isso pode bloquear outras corrotinas e alongar ciclos, mas **o atraso real não foi medido**. Já existe isolamento de threads para a migration do lifespan da API (`api/application_runtime.py:53`), não para os CRUDs de runtime. A 9.3, portanto, não está concluída: este relatório fecha o mapa inicial; a implementação requer instrumentação, escolha de fronteira e piloto.

## 2. Método e limites da evidência

A revisão combinou busca AST de funções `async def` e métodos SQL identificáveis no `DatabaseManager`, busca de aliases e métodos de persistência, leitura dos chamadores e revisão independente por três recortes (API/worker/core; execution/risk; infraestrutura/scripts). O checkout de auditoria permaneceu limpo durante as revisões e foi baseado no SHA de `master` pós-PR #24.

“Confirmado” significa que o caminho estático async → helper síncrono → `Session`/SQL foi rastreado no código. Isso prova execução síncrona no thread chamador quando aquele ramo é alcançado; **não quantifica** a duração, frequência, saturação de pool ou impacto de cauda. Não havia ambiente PostgreSQL/Redis VPS em execução para tracing/benchmark, e CI com PostgreSQL não é medição de performance. A varredura lexical não substitui tracing dinâmico nem é uma análise completa de fluxo interprocedural.

## 3. Arquitetura de persistência e isolamento já existente

- `database_manager.py:14-28` cria `Engine` síncrono e `SessionLocal` síncrona. Os métodos SQL instanciam a Session localmente e a fecham dentro do próprio helper; intents, snapshots de reconciliação e proteções usam `finally: db.close()`. Diversos métodos CRUD mais antigos fecham somente no caminho normal, sem `finally`, então uma exceção entre abertura e fechamento pode deixar limpeza dependente do GC.
- Não foi encontrado indício de que uma instância ORM `Session` seja armazenada como atributo, compartilhada entre tarefas ou passada por um `await` de rede nos fluxos examinados. **Não converter essa observação em licença para compartilhar Session em threads:** cada operação offloaded precisa abrir, usar e fechar sua Session inteiramente dentro do worker.
- `api/application_runtime.py:53` executa `db_manager.create_tables` via `await asyncio.to_thread(...)`; é um isolamento pontual do DDL/Alembic no startup da API. Em contraste, `worker.py:26` chama `db_manager.create_tables()` diretamente dentro de `run_worker()` assíncrona.
- Mesmo na API, `api/application_runtime.py:54` chama o construtor síncrono `TradingManager` no loop. `core/manager.py:33-37` chama `RuntimeConfigRegistry.apply_to_settings`; `core/runtime_registry.py:21-35` faz `inspect(engine).has_table()` e duas consultas síncronas de configuração. Isso deixa I/O de configuração no startup, apesar da migration ter sido offloaded.
- Offloads já existentes em `core/data_feeds.py` protegem gravações de incidentes/order book; `infra/async_http.py` isola operação HTTP legada, e `infra/redis_cache.py` isola chamadas Redis síncronas. Esses exemplos **não** isolam os helpers SQL do `DatabaseManager`.
- `scripts/optimize_db.py:13-57` é um utilitário separado que usa `create_async_engine`, `async with` e `await conn.execute`. Não é o backend de produção nem um repositório async compartilhado. Não foi encontrado `AsyncSession`/`async_sessionmaker` no caminho de runtime examinado.

## 4. Chamadas síncronas confirmadas por prioridade

### P1 — submissão, intents, reconciliação e risco

`OrderManager.submit` (`execution/order_manager.py:133-206`) aguarda rede para dados de mercado/saldo, mas lê `get_account_state` em `:174` diretamente; `_circuit_breaker_reason` (`:121-131`) lê `get_daily_pnl` em `:124`. Essas chamadas levam a `SessionLocal` e `query()` em `database_manager.py:65-69, 212-221`. `RiskAI.validate_order` também é síncrono e pode alcançar mais leituras, mas `get_verified_risk_periods` e `get_verified_trade_returns` retornam `None` por desenho (`database_manager.py:223-240`), mantendo o risco fail-closed; não se deve assumir que todos os ramos posteriores são alcançados.

`OrderReconciler.submit_with_retry` (`core/reconciliation.py:139-215`) chama `reserve()` (`:53-56`), `get_order_intent()` e múltiplos `update_order_intent()` sem offload, antes e depois de `await send(...)`. Os helpers em `database_manager.py:747-795` fazem query, insert/update, `commit` e `refresh`, cada um com Session própria. `reconcile()`/`sync_positions()` (`core/reconciliation.py:224-318`) leem intents/posições e gravam snapshots (`database_manager.py:797-823`) no loop. A quantidade de consultas pode crescer com intents em recuperação.

**Invariante de desenho:** a reserva durable da intent deve continuar concluída antes de enviar à exchange; transições após resposta também devem ser persistidas e recuperáveis. Não reter Session/transaction aberta através de `await` de rede e não converter gravações de estado de ordem em `fire-and-forget`. Os commits separados representam etapas de uma saga com recuperação/reconciliação, não uma transação atômica com a exchange.

### P1 — persistência de posição/fill e proteção OCO

`ExecutionEngine._persist_entry/_persist_exit` (`execution/execution_engine.py:60-101`) são corrotinas, mas invocam diretamente `upsert_runtime_position`, `create_position`, `close_runtime_position` e `close_position` (helpers síncronos em `database_manager.py:72-152`). A escrita é best-effort após a ação do adapter; entry atualiza runtime position e `positions` por commits separados, exit também atualiza duas representações separadamente. Uma falha pode deixar estado local/Redis divergente da exchange e bloquear o loop durante a escrita.

`OCOManager.attach_protection/cancel_for_parent` (`execution/oco_manager.py:47-133`) chama inline `upsert_protection_order`, `list_active_protection_orders` e `update_protection_order` (`database_manager.py:825-865`) entre awaits de rede. Há estados `pending`/resposta remota em etapas; cancelamento ou falha parcial requer reconciliação, não retry cego.

### P1/P2 — ciclos do motor e memória de padrões

`RoboTraderUnified.start` (`core/engine.py:208-755`) chama métodos síncronos no ciclo de análise: conta/PnL (`:483-488`), observações e snapshots shadow (`:571, 635`), logs, e leituras/escritas contábeis depois de uma execução (`:715-739`). Entre os caminhos indiretos, `PatternMemory.find_match` (`core/pattern_memory.py:119-136`) consulta até 5.000 padrões por chamada através de `get_market_patterns`. Esses caminhos podem repetir por símbolo/ciclo; latência e frequência precisam ser medidas, não inferidas pelo LOC.

`SniperEngine.start` (`core/sniper_engine.py:61-402`) também lê conta/PnL, grava observações/snapshots e histórico de execução dentro de corrotina. `TradingManager.trigger_kill_switch` (`core/manager.py:115-122`) registra o evento com commit síncrono depois do pedido ao connector; isso pode aumentar a latência do endpoint de kill switch. A ordem de persistir e reportar o resultado deve ser revisada sem reduzir a prioridade operacional do kill switch.

### P2 — API, startup e ingestão

- `api/routers/operations.py:42-71` (`/status`) realiza três leituras SQL sequenciais; `:110-132` (`/logs`) chama `get_system_logs` sincronamente, que materializa registros sem limite (`database_manager.py:702-709`). Ambos são `async def`.
- `api/routers/health.py:17-25` chama `health_payload` síncrona inline; a função usa `engine.connect()/exec_driver_sql("SELECT 1")` e consulta observações (`api/runtime_services.py:58-99`, `database_manager.py:345-352`). Health check pode disputar o mesmo loop/DB.
- `api/routers/engines.py:21-32` chama reload síncrono; `TradingManager.reload_runtime_config` (`core/manager.py:87-92`) reconsulta profile e `inspect(engine)` via `RuntimeConfigRegistry`.
- `data/news_processor.py:256-296, 552-588` grava snapshots de tendência/artigos por meio de `DatabaseManager` dentro de corrotinas alcançadas pelas rotas/feeds. As gravações de incidentes/order book em `core/data_feeds.py` têm offload, mas news/trend não.
- `worker.py:18-30` executa migration e constrói `TradingManager` dentro da coroutine; tanto `create_tables` (`database_manager.py:30-41`) quanto leitura do profile durante o construtor podem bloquear o loop de inicialização.

### P2/P3 — backtest e utilitários async

`BacktestEngine.run` (`core/backtest_engine.py:108-340`) grava `DecisionSnapshot` via `create_decision_snapshot` em cada barra (`:319`); `risk/strategy_optimizer.py:65-124` pode multiplicar isso ao aguardar vários backtests. É um caminho de batch/histórico, não uma ordem live, mas pode ocupar longamente o event loop do processo que o executa.

Ferramentas CLI assíncronas também chamam DB sync: `scripts/ingest_news.py`, `final_readiness_check.py`, `run_upgrade2_replay.py`, `run_shadow_replay.py`, `e2e_demo_simulation.py`, `run_monthly_backtest.py` e `replay_decision_snapshots.py`. Foram separadas do runtime 24/7 no inventário; seu impacto primário é duração/throughput do job. `scripts/optimize_db.py` usa SQLAlchemy async de modo próprio. Scripts puramente síncronos não entram no problema de event loop.

## 5. Inventário quantitativo indicativo

Na busca AST por chamadas de corrotinas a métodos ORM do `DatabaseManager`, os arquivos com mais call sites foram: `core/engine.py` (13), `core/reconciliation.py` (12), `core/sniper_engine.py` (8), `execution/oco_manager.py` (6), `api/routers/operations.py` (4), `execution/execution_engine.py` (4), `data/news_processor.py` (2) e `execution/order_manager.py` (2), além de scripts. A contagem **59/24/15** cobre chamadas diretas reconhecíveis pelo padrão de alias; wrappers (health, registry, pattern memory, RiskAI, startup) acrescentam caminhos não contados. Ela serve para delimitar trabalho, não para classificar risco por volume nem medir execução.

Não há baseline observado de query/commit, espera de pool, atraso do event loop ou duração de ciclo. Os testes PostgreSQL no CI provam comportamento funcional coberto, não p50/p95/p99, saturação, tempo de resposta sob banco lento ou soak.

## 6. Guardrails para implementação

1. **Nenhuma Session compartilhada.** Para offload, passar ao worker somente argumentos/DTOs; o helper abre, usa e fecha a Session na própria thread. Não passar `Session`, ORM session state ou conexão ao `asyncio.to_thread`.
2. **Nunca segurar transação durante rede.** Reservar/commitar intent, soltar sessão, fazer `await` externo, então persistir resultado em operação separada. Preservar a recuperação de estado ambíguo já existente.
3. **Thread offload não cancela o trabalho já iniciado.** Cancelar a coroutine que aguarda `asyncio.to_thread` não interrompe com segurança a função de banco rodando. Para writes, projetar idempotência/resultado reconciliável, observar conclusão e não repetir cegamente após `CancelledError`.
4. **Executor limitado e backpressure.** Se for escolhida compatibilidade sync com threads, evitar fila ilimitada e saturação do default executor compartilhado; estabelecer concorrência/timeout e telemetria. O executor deve ser dono do lifespan e fechar ordenadamente.
5. **AsyncSession é alternativa arquitetural, não troca textual.** Definir engine/driver compatíveis, lifecycle, transaction scope, pool e sessão curta por operação/unidade de trabalho. Não compartilhar `AsyncSession` entre tasks nem mantê-la aberta em awaits de exchange/provider.
6. **Não enfraquecer fail-closed.** Falha, timeout ou estado inconclusivo de persistência em intent/posição mantém entradas bloqueadas e exige reconciliação. Shadow/telemetria não devem ser elevados a autorização de risco. `LIVE_TRADING_ENABLED=false` e todas as flags de autonomia permanecem OFF.

## 7. Plano de rollout incremental

**Etapa A — baseline e desenho (antes de alterar callsites críticos):** instrumentar duração por classe de operação sem registrar parâmetros sensíveis; acompanhar p50/p95/p99/max de query/commit, pool checkout/wait/checked-out, event-loop lag p95/p99/max, latência de ciclo por engine/símbolo, fila/rejeições do executor, falhas/timeouts de persistência e idade/divergência de posições/intents. Medir em ambiente isolado/shadow com carga representativa. Alvos numéricos de aceite não foram inventados; definir depois de uma baseline real.

**Etapa B — piloto reversível de baixa criticidade:** selecionar uma leitura da API (`/status`/`/logs`, após definir semântica e limite de logs) ou uma gravação analítica shadow (`AIObservation`/`DecisionSnapshot`) sem caminho de autorização/ordem. Offload síncrono completo com executor limitado, feature flag se necessário, await do resultado (sem fire-and-forget), testes de conteúdo/ordenação/falha/cancelamento/conexão e comparação antes/depois. A mudança de piloto não deve alterar formato público nem descartar registros.

**Etapa C — observabilidade e loops:** após o piloto, migrar grupos de chamadas coesas do engine/reconciliação, mantendo cada operação de banco como unidade curta. Medir backpressure e comportamento sob banco lento; não agrupar queries em uma Session compartilhada entre corrotinas.

**Etapa D — caminho de ordem por último:** apenas com teste de fault injection e revisão de domínio, tratar reserve/update intent, proteção, position/fill e snapshots. Cobrir falha de DB antes do envio, depois de resposta remota, após fill, durante cancelamento e durante restart; duplicidade/idempotência, concorrência na chave única, divergência Redis/PostgreSQL/exchange, pool exaurido e shutdown. Sem persistência verificável, o caminho mantém bloqueio fail-closed.

### Critérios de aceite propostos

- Nenhum acesso ORM sync executado inline em coroutine nos escopos migrados, verificado por teste/static audit direcionado.
- Nenhuma `Session` compartilhada ou mantida através de I/O de rede; criação/fechamento observados sob sucesso, erro e cancelamento.
- Nenhuma perda/duplicidade de intent, fill, posição, proteção ou snapshot em falha simulada; reconciliação mantém estados incompletos em bloqueio.
- Medidas antes/depois mostram event-loop lag e ciclo do motor; pool/worker sem backlog crescente ou leak durante soak controlado.
- Todos os testes de risco e flags continuam fail-closed; nenhum teste ou migração ativa live/autonomia.

## 8. Decisão e próximo passo

O diagnóstico inicial da 9.3 está concluído como **auditoria estática**, mas a subfase permanece **em andamento**: ainda não foi escolhido entre isolamento síncrono em executor limitado e migração de partes para SQLAlchemy async, não há instrumentação de baseline e nenhum call site de produção foi alterado. Recomenda-se começar instrumentando e escolher piloto de baixa criticidade, e deixar intents, reconciliação, posições e proteções para etapa posterior. A 9.3 não autoriza VPS, trading autônomo ou capital real.

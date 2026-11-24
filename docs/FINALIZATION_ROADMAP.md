# Plano de finalização — ZIA-TRADER v17, backend em validação

**Atualizado:** 2026-11-19. **Base atual:** master pós-PR #33, SHA `10168db2bf49ebdf47c1c1fbb0f25ea6e463591d`; PR33 squash-merged, branch preservada e CI pós-merge verde. O incremento ZT01 está em `fix/zt01-control-plane-and-client-scope`: 421 testes locais, 5 skips e 1 warning; CI/review/aceite da nova PR são gates próprios. Métrica cumulativa: 7/16 gates aceitos, 43,75%, vinculados à baseline PR33; não é percentual de segurança, lucro ou autorização operacional. O objetivo segue pré-produção supervisionada, com live desabilitado.

## Estimativas históricas de engenharia — não representam o estado atual

Os percentuais abaixo são mantidos apenas como histórico, não uma medida vigente de prontidão, contagem de linhas, probabilidade de lucro ou certificação. Para aceite atual usar gates verificáveis, relatório de 2026-11-19 e evidência da PR associada.

| Dimensão | Estimativa | Evidência e limitador dominante |
|---|---:|---|
| Arquitetura backend e controles de segurança | **75–80%** | Alembic/PostgreSQL, gates fail-closed, OrderManager, reconciliação, controles de risco, logs e regressões temporais existem; ledger financeiro verificável, SAST completo e revisão humana independente continuam pendentes. |
| Estrutura de engenharia e testes locais | **78–80%** | Fase 8A integrada; Fase 9.1 e 9.2 integradas; PR #23 teve 220 testes locais e 223 no CI/PostgreSQL; validação local desta auditoria na branch de correções: 235 passed, 3 skipped, 1 warning. |
| IA/dados prontos para validação OOS | **25–30%** | Pipeline walk-forward/registry/drift está presente; falta dataset real licenciado/proveniente e modelo validado/aprovado. |
| VPS e operação 24/7 comprovadas | **30–35%** | Compose e container build no CI existem; não houve boot, PostgreSQL/Redis persistentes, TLS, backup/restore, alertas ou restart test em VPS alvo. |
| Autonomia real autorizável hoje | **0% habilitado; cerca de 10% de prontidão de engenharia** | Flags reais continuam OFF; equity/trade ledgers inexistentes e não há soak Demo/Testnet. Não habilitar execução autônoma real nesta situação. |
| **Prontidão geral para VPS supervisionada com negociação** | **aprox. 40/100** | Estimativa conservadora e arredondada: código maduro não substitui proveniência financeira, modelo, homologação de venue, restore, operação contínua e aprovação humana. |

O repositório está mais adiantado que a prontidão do sistema para assumir risco. “75% de estrutura” não significa “75% seguro para operar dinheiro”.

## Fases finais propostas

### Fase 8A — Dependências e build reproduzível (**concluída e integrada — PR #20**)

- **Defeito:** o lock anterior foi exportado de um ambiente diferente e continha `nvidia-cusparselt-cu13` (`manylinux2014_sbsa`), enquanto a virtualenv ativa do Sandbox é ARM64. O Dockerfile e CI instalavam `requirements.txt`, ignorando o lock; portanto o lock não era nem usado nem portátil.
- **Correção concluída:** resolver Torch em backend CPU explícito, fixar dependências por versão e SHA-256, remover artefatos CUDA/NVIDIA desnecessários para VPS CPU, sincronizar lock em CI/Docker e executar `uv pip check`.
- **Aceite:** venv limpo ARM64, Torch CPU sem CUDA/NVIDIA, `uv pip check` passou e 192 testes passaram. Jobs `test` e `container` do PR #20 verdes (runs `39651671722` e `39652262792`); imagem construída em runner GitHub x86_64. Build ARM e execução do Compose/VPS continuam não testados.

### Fase 8B — Ledger financeiro e reconciliação

Implementar, em migração aditiva e compatível, eventos imutáveis de intents, ordem externa, fills parciais/completos, comissões, funding, depósitos/saques e snapshots de saldo/posição. Definir fonte autoritativa por adapter, chaves de idempotência, timestamps UTC, `Decimal`, completude/late data, reconstrução após restart e reconciliation. Construir `equity_ledger_v1` e `closed_execution_ledger_v1` somente a partir de eventos rastreáveis. Não converter dado ausente em zero. Cobrir duplicatas, atrasos, concorrência, cashflow, fees, funding e fronteiras UTC em testes determinísticos. **Entradas seguem bloqueadas até revisão de domínio, integração mock e evidência read-only/Demo confiável.**

#### Subfase 8B.1 — fundação de evidências audit-only (**em andamento; não homologada**)

- Migration aditiva `a5c74e8d2b91` cria `equity_ledger_v1`; o writer exige identidade estável por origem, UTC explícito, `Decimal`, componente/unidade semântica e SHA-256 do registro canônico. Replays idênticos são idempotentes; a mesma chave com payload diferente é rejeitada. PostgreSQL impede UPDATE/DELETE/TRUNCATE; SQLite de teste impede UPDATE/DELETE e rejeita round-trip decimal com perda.
- `EQUITY_LEDGER_CAPTURE_ENABLED=false` por padrão e configurado no lifespan. Nenhum adapter, endpoint ou fluxo atual produz eventos automaticamente; os dados são declarações fornecidas pelo chamador, não autenticados pela tabela nem por hash de cadeia.
- `get_verified_risk_periods` e `get_verified_trade_returns` continuam retornando `None`; esta subfase não agrega equity, não cria `closed_execution_ledger_v1`, não altera RiskAI/sizing/ordens e não libera entradas.
- Validação local (2026-11-06): **266 passed, 4 skipped, 1 warning**; os skips exigem `TEST_DATABASE_URL`. CI do PR #31, run `42245099706`, executou PostgreSQL e passou: **270 passed, 1 warning**, jobs `test`/`container` verdes no SHA `956a4100e42c29dd58ee5ad8f9a27042753bb161`. O PR [#31](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/31) foi squash-merged em 2026-11-06 no commit `ea5dae770c554aa0e759c4610c739af5a0f66a7f`; CI pós-merge run `42253108432` passou `test` e `container`. A branch `feat/audit-only-equity-ledger-8b` foi mantida. CodeRabbit ficou `SKIPPED`, sem revisão humana registrada. CI não valida deployment/staging. Ainda faltam produtores/adapters homologados, completude/reconciliação/cashflows, fee/funding, recuperação concorrente sob carga e privilégios DB separados antes de considerar o ledger verificável. Relatório: `docs/reports/phase8b.1_equity_ledger_audit_only_2026-11-05.md`.

### Fase 8C — Dados de mercado e aprovação de modelo

O operador precisa selecionar/prover uma fonte de dados autorizada para os instrumentos e período pretendidos. Registrar licença/origem, timezones, ajustes, cobertura/gaps, SHA-256 e maturidade de labels. Executar treinamento reprodutível e walk-forward com purge/embargo, OOS por regime, custos e slippage; comparar buy-and-hold/sinal determinístico; avaliar calibração e drift. Ausência de dados ou gate não aprovado continua `HOLD`. Não fabricar dataset ou artefato aprovado.

### Fase 8D — VPS de staging e segurança operacional

Escolher arquitetura/OS/região e provedor alvo; fornecer/autorizar ambiente **staging isolado** sem capital real. Validar `docker compose config`, build, migrations, volumes PostgreSQL/Redis, health/readiness, shutdown/restart, falhas de dependência, proxy TLS, firewall, SSH, NTP, secrets, rate limit, CORS e logs. Fazer backup e restore em banco separado e medir recursos. CI build verde não prova nenhum desses itens.

### Fase 8E — Trading autônomo apenas em shadow/paper e Demo/Testnet supervisionado

Antes de considerar autonomia, executar primeiro shadow/paper sem rota de ordem; provar que decisão, sizing, proteção, shutdown e reconciliação ficam consistentes. Depois, se o usuário selecionar e configurar explicitamente uma venue Demo/Testnet e houver gates aprovados, ensaiar timeout ambíguo, fill parcial, restart e kill switch. Exigir diário auditável, limites conservadores e acompanhamento humano; qualquer estado incompleto bloqueia novas entradas. Isso não autoriza mainnet.

### Fase 8F — Soak, auditoria e aceite

Operar em staging contínuo por janela acordada, revisar alertas, drift, disco, atraso de feed, falhas, backups e latência; demonstrar restore e rollback. Fazer revisão de segurança independente, LGPD/retention/export/delete, resposta a incidente e responsabilidade operacional. A autorização de qualquer modo de live é uma decisão humana separada, depois da evidência, e não será ativada automaticamente pelo código ou por um merge.

### Fase 9 — auditoria arquitetural e preparação para operação autônoma supervisionada

**Iniciada em 2026-10-22.** A Fase 9 parte do diagnóstico anexado pelo usuário e se concentra em fronteiras de runtime, async real e contratos de integração; não muda estratégia, thresholds, sizing ou autorização de ordens.

- **9.1 — lifecycle ASGI (concluída e integrada — PR #21):** mover construção de `DatabaseManager`/`TradingManager` e migration da importação para lifespan; fazer migration em thread; runtime ausente retorna 503; separar stop reiniciável dos motores do shutdown de recursos. CI run `39812717326`: jobs `test` e `container` verdes; CodeRabbit marcou revisão manual como ignorada. Evidência: `docs/reports/phase9_architecture_audit_2026-10-22.md` e testes `test_application_runtime.py`, `test_manager_lifecycle.py`, `test_api.py`.
- **9.2 — app factory, routers e gates (concluída e integrada — PR #23):** `main.py` reduzido a entrypoint de 12 linhas; 5 routers preservam 24 combinações de rota; runtime e tasks isolados por `app.state`; start/stop linearizados por lock comum; API e worker bloqueiam config production insegura antes de inicializar runtime; scanner AST limitado tem regressões no pytest, mas não é gate de segurança; `.dockerignore` exclui payloads privados/dados e preserva `data/news_processor.py`. CI run `40046660678`: job PostgreSQL **223 passed, 1 warning** e job container construiu imagem e aprovou smoke de import. CodeRabbit marcou revisão como `Review skipped`; não equivale a revisão humana. Nenhum `docker compose up` ou VPS foi validado. Evidência local: `220 passed, 3 skipped, 1 warning`. Relatório: `docs/reports/phase9.2_codebase_map_2026-10-23.md`.
- **9.3 — persistência não bloqueante (auditoria estática inicial concluída; migração pendente):** mapeamento encontrou 59 chamadas reconhecíveis a métodos ORM síncronos em 24 corrotinas/15 arquivos (limite inferior, sem wrappers interprocedurais); pontos prioritários incluem intents/reconciliação, gates pré-ordem, persistência pós-fill/OCO, ciclos dos motores, health/status e startup do worker. A migration do lifespan da API usa `asyncio.to_thread`, mas CRUDs não; `TradingManager` lê profile SQL no construtor e o worker chama `create_tables()` inline. Não foi encontrada Session atravessando awaits nos fluxos examinados. Nenhuma latência foi medida e nenhum call site foi alterado. Próximo: baseline real e piloto reversível de baixa criticidade com executor limitado ou fronteira async definida, antes de tocar no caminho de ordens. Relatório: `docs/reports/phase9.3_persistence_async_audit_2026-10-23.md`.
- **9.4 — stream de mercado read-only:** implementar protocolo/adapter só depois da seleção de venue/fonte; cobertura obrigatória de gaps, sequência, heartbeat, reconexão, staleness e backpressure.
- **9.5 — execução em Demo/Testnet supervisionado:** ensaiar intent/idempotência, partial fill, timeout, restart e kill switch após gates de ledger/dataset; mainnet não é parte da Fase 9 inicial.
- **9.6 — LLM opcional e isolado:** não é requisito para core trader. Se houver caso de uso aprovado, restrito a sumarização read-only estruturada e sem caminho para `RiskAI`/`OrderManager`.

**Estado da Fase 9 como um todo:** em andamento; 9.1 e 9.2 estão integradas; a auditoria inicial 9.3 foi concluída, mas a migração e medição ainda estão abertas; 9.4+ não iniciadas. Suíte local de 9.2: `220 passed, 3 skipped, 1 warning`; CI PR #23 com PostgreSQL: 223 passados; PR documental #24 (`eeee740`) atualizou evidências pós-merge e passou `test`/`container` no run `40047113792`. CodeRabbit marcou `Review skipped`; não há revisão humana registrada. CI/build não significa aprovação de produção, ledger, dataset ou VPS. Manter live/autonomia OFF.

## Próximo passo executável

Instrumentar baseline de SQL/pool/event-loop em ambiente isolado; então escolher e testar piloto reversível de baixa criticidade, mantendo Session criada/usada/fechada dentro da thread ou transação async curta. Não iniciar offload fire-and-forget nem migrar a reserva de intent/fill antes de testes de cancelamento, idempotência e reconciliação. Em paralelo, ledger 8B e requisitos de dados 8C continuam bloqueadores — não substituir fontes reais por fixtures como prova de mercado. Só depois de ledger/dataset e escolha explícita de ambiente avançar para staging. Manter `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, `AUTO_START_ENGINES=false`, `AUTONOMOUS_TRADING_ENABLED=false`, `MANUAL_TRADING_ENABLED=false`, `NEURAL_MODELS_ENABLED=false` e `BACKTEST_USE_ENSEMBLE=false`.

## Limites e decisões externas

Para avançar a testes de integração são necessários: definição do alvo VPS (arquitetura/OS), escolha de fornecedor autorizado de dados, e venue Demo/Testnet pretendida. Não são necessários para a resolução local 8A. Credenciais de live ou de carteiras não devem ser solicitadas nem usadas nesta etapa.


## Adendo de auditoria — 2026-11-02

A branch `fix/audit-nov-2026`, baseada no `master` pós-PR #25 (`cfcec0e`), corrigiu a semântica de fill zero/parcial e de estados de ordem desconhecidos/terminais, tornou auth demo explicitamente opt-in e alinhou `LIVE_KILL_SWITCH` para true por default e no `.env.example`. O teste de defaults confirma live/manual/autonomia/autostart/neural OFF e shadow/kill switch ON. O simulador E2E agora exige atenção e bloqueia preflight diante de intents abertas/parciais.

Validação local atual: **235 passed, 3 skipped, 1 warning**; `compileall`, `git diff --check` e `uv pip check` passaram. O inventário encontrou 194 módulos Python e 27.855 linhas físicas. A triagem AST não detectou padrões suportados; `pip-audit` não reportou CVEs conhecidas no venv verificado. Isso não é auditoria SAST/DAST nem aprovação de segurança independente. Há 77 versões mais novas listadas pelo índice, incluindo saltos major; upgrade massivo foi deliberadamente separado para evitar misturar migrações de API com a correção de execução.

A atualização não conclui a Fase 9.3: permanecem 59 chamadas ORM síncronas reconhecíveis em corrotinas segundo o inventário estático anterior, sem benchmark de latência e sem migração aplicada. As Fases 8B (ledger), 8C (dataset/OOS), 8D (VPS staging), 9.4 (feed read-only homologado), 9.5 (Demo/Testnet) e 8F (soak/aceite) continuam abertas. Não recalcular a pontuação de prontidão sem fechar evidência operacional. `LIVE_TRADING_ENABLED=false` e todas as flags de autonomia/manual continuam OFF.

Relatório e fluxo lógico: `docs/reports/audit_2026-11-02.md` e `docs/reports/zia_logic_flow_2026-11-02.mmd`.


### Evidência de integração — PR #26 (2026-11-02)

O PR #26 foi squash-merged após `test` e `container` passarem no CI; CodeRabbit foi `SKIPPED`. SHA de integração: `4c260bf4c74227dbe5ad6e3825c57b3fd01262db` (`master` sincronizado). A suíte local correspondente foi 235 passed, 3 skipped, 1 warning. Este é fechamento de código/documentação, não aceite de deployment: ledger 8B, dados/OOS 8C, persistência async 9.3, staging VPS 8D e soak continuam pendentes; trading live/autônomo permanece bloqueado.


## Expansão incremental de inteligência — Fase 10.1 (2026-11-03)

Esta primeira subfase implementa somente um veto adicional de alinhamento de tendência, conforme a proposta `novahabilidades.txt`; não declara a nova capacidade de inteligência de mercado completa. O `TrendAlignmentFilter` reutiliza o `MarketRegimeDetector`, o detector causal de reversão, o fluxo de livro já disponível, a avaliação de microestrutura/custos e os gates existentes. Em tendência forte, uma entrada na mesma direção passa apenas por este filtro; uma entrada oposta exige reversão detectada `from`/`to`, confiança mínima nunca inferior a 0,70, order flow completo e concordante, microestrutura aprovada e circuito de risco não disparado. Regime `high_volatility`, `unknown`, `uncertain`, `news_shock` e `liquidity_crisis` bloqueiam novas entradas. Falha gera `HOLD`/confiança zero no engine; `OrderManager` rejeita ordens IA sem validação explícita do gate. Esse resultado não substitui autorização final, ledger, reconciliação ou RiskAI.

Não foram alterados pesos de modelos, fórmulas, sizing, critérios existentes de risco, dependências, credenciais ou flags. Não se envia ordem pela nova camada; entradas reais/autônomas continuam desativadas. Validação local final: **246 passed, 3 skipped, 1 warning**; `compileall`, `uv pip check` e `git diff --check` passaram; a triagem AST não detectou padrões suportados. O diagrama foi renderizado e inspecionado. O PR [#28](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/28) foi integrado em 2026-11-03; CI `test` e `container` aprovados; CodeRabbit `SKIPPED`. SHA de `master`: `60e92a551f08dca6034ebb48059d7b2418186402`.

Conectores e coleta: o agente desta sessão tem acesso ao MCP CoinGecko e Supabase; Alpha Vantage aparece configurado, mas sua descoberta de ferramentas falhou por autenticação nesta sessão. Isso não expõe MCP ao processo Python. A aplicação já possui RSS/GDELT, CoinGecko Trending e provedores opcionais por API key; `scripts/ingest_news.py` é um CLI de execução pontual que persiste artigos/tendências quando invocado; o collector VPS do Binance público grava snapshots em arquivos a cada 60 s quando o profile `collector` é ativado. ScheduleTask/Triggers do Manus não foram criados e não gravam por si só no Postgres do Trader. Para alimentação recorrente do banco, a rota adequada é um worker/CLI próprio, com credenciais de leitura mínimas armazenadas como secrets do deployment, validação de origem/timestamp/licença, deduplicação/idempotência e persistência auditável. Ver relatório `docs/reports/phase10.1_market_intelligence_trend_alignment_2026-11-03.md` e fontes `docs/reports/market_intelligence_source_notes_2026-11-02.md`.

Permanecem para etapas futuras: `NewsIntelligenceEngine`/`EventImpactAnalyzer` com novidade, confiabilidade/proveniência, impacto de evento e surprise; validação licenciada e OOS; indicadores adicionais de fluxo como volume agressor/CVD/open interest; estratégias adaptativas e avaliação de risco/execução sem duplicar os componentes atuais; replay histórico, integração e stress. Nenhuma destas funções foi marcada como concluída nesta subfase.


## Ingestão read-only unificada — Fase 10.2 (2026-11-04)

O branch `feat/unified-readonly-market-ingestion` adiciona `UnifiedMarketDataCollector`, schema de candles com identidade composta de provedor/classe de ativo, upsert idempotente e `POST /market-data/collect` protegido por admin. A rota tem payload estrito, feature gates independentes desligados por default e dry-run default. Binance Public é suportado para crypto; Alpha Vantage é limitado a equity/FX diário com chave separada. Yahoo permanece bloqueado e CoinGecko é catalogado somente como contexto agregado, fora do schema OHLCV.

A validação local fechou em **256 passed, 3 skipped, 1 warning** com o lock e Torch CPU. Corrigimos o contrato de rota do teste, ligamos a nova migration ao head Alembic anterior e atualizamos a regressão de downgrade para comprovar que a identidade do provider não pode ser descartada quando isso causaria colisão. O upsert passou teste SQLite real de correção idempotente e separação por provider. O coletor também propaga corretamente o cancelamento assíncrono. O smoke read-only via API, `CoreCommandManager` e Binance retornou 4 candles fechados em dry-run, zero persistidos e zero ordens. Relatório detalhado: `docs/reports/phase10.2_unified_market_ingestion_validation_2026-11-04.md`.

**Status pós-merge:** o PR [#30](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/30) foi squash-merged em `master` em 2026-11-04; commit `16a7326deb373a477d2ece003de657168ae7f9a2`. A branch `feat/unified-readonly-market-ingestion` foi preservada conforme solicitado. O CI pós-merge run `41846291110` concluiu `test` e `container` com sucesso. CodeRabbit ficou `SKIPPED`, sem revisão humana registrada. Não houve deployment, staging/VPS nem homologação de persistência operacional ou licenças. Os gates `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, autonomia/manual/autostart continuam inalterados; o merge não declara prontidão para operação real.

## Auditoria corretiva e hardening arquitetural — 2026-11-10

A revisão partiu do `master` pós-PR #31 (`ea5dae770c554aa0e759c4610c739af5a0f66a7f`) na branch isolada `fix/phase9-nov9-fail-closed-hardening`. O diff ainda não está integrado e as estimativas de prontidão do início deste documento não foram recalculadas.

- **Execução fail-closed:** autorização global é revalidada no adapter Mainnet e no MarketConnector; Mainnet exige `client_order_id` e propaga `newClientOrderId`. CCXT/MT5 não submetem ordens até existir idempotência e reconciliação remota homologadas, mesmo com flags ativadas em teste. Retentativa ampla por `TypeError` foi removida. Isso não autoriza nem valida execução Mainnet.
- **Concorrência e persistência:** cancelamento de engine preserva `CancelledError` e limpa leases; upsert rejeita duplicata conflitante; `/core/sync` tem esquema estrito, limites de símbolos/candles e fan-out limitado. O endpoint externo de candles continua read-only com feature gate independente.
- **Infraestrutura:** Compose propaga ao preflight somente as variáveis TLS não secretas; o container API não monta a chave privada. TLS usa hostname/SNI do certificado e `TLS_PREFLIGHT_CONNECT_HOST=nginx` para alcançar `nginx:443`. Backup Redis verifica status/contador e protege cada chamada Docker com GNU `timeout` (75 s para snapshot, 600 s para operações gerais). CI executou PostgreSQL 16 efêmero, build de imagem e smoke de imports; staging e integrações reais continuam pendentes.
- **Validação local final:** **310 passed, 4 skipped, 1 warning** localmente. CI run `42836399864` no SHA `4893d18`: **314 passed, 1 warning** no job PostgreSQL e build/smoke do container aprovados. O workflow alinha cliente e servidor PostgreSQL 16 após o erro `SET transaction_timeout = 0`; CodeRabbit foi ignorado. PR #32 está aberta/limpa, sem revisão humana registrada (`reviewDecision` vazio); staging continua pendente.
- **Ainda pendente:** medição/migração das chamadas ORM síncronas (9.3), stream de mercado homologado (9.4), ledger fechado e fonte de dados licenciada/OOS, restore real em staging e soak. As flags live, manuais, autônomas e autostart ficam OFF.

Relatório e diagrama de fronteiras: `docs/reports/phase9_architecture_hardening_2026-11-10.md`.


### Follow-up de hardening — revisão independente e P2 corrigidos (2026-11-10)

A revisão independente inicial encontrou dois P2 (hostname TLS incompatível e timeout sem limite por comando); ambos foram corrigidos. O follow-up revelou que as variáveis não eram propagadas ao serviço API pelo Compose e que o preflight não podia inspecionar a chave privada sem montá-la no API; o Compose agora encaminha apenas configurações não secretas, e o handshake contra Nginx ativo substitui os checks locais de arquivo. A cobertura de timeout foi ampliada para dump PostgreSQL, execução Redis e todas as cópias, além de regressão do contrato YAML. Suíte local: **310 passed, 4 skipped, 1 warning**. CI `42836399864` no SHA `4893d18` passou com **314 passed, 1 warning** e build/smoke do container. Revisão humana da PR #32 não está registrada; CodeRabbit foi ignorado. TLS/Redis real e staging seguem pendentes; live/autonomia desligados.


## Estado atual — backend, conectores e sandbox (2026-11-19)

A PR #32 foi integrada por squash autorizado em `master` no commit `56c20252e28605e3c6568bbcd3ebbf0c3935a6a5`, preservando `fix/phase9-nov9-fail-closed-hardening`. O CI pós-merge da Fase 9 foi acompanhado na etapa anterior. Notas de PR/CI pendentes de 2026-11-10 acima são histórico, não o estado atual do merge.

O incremento `fix/backend-provider-security-nov19` deriva dessa master e se limita ao backend: catálogo admin-only sem segredos, redaction de Settings/health/logs, cache particionado por autenticação com chaves HMAC, allowlist HTTPS de notícias, ausência de redirects e de proxy/CA herdados, opt-in de provedores com chave, persistência de notícias/tendências fora do loop com sessões próprias e smoke público sem execução. Não modifica pesos, sizing, ledger audit-only ou bloqueios live.

O teste real coletou 119 candles fechados de BTC/USDT 1h, persistiu/reimportou 119 linhas sem duplicação e verificou 10 features com 86 linhas válidas. O core rejeitou a candidata de compra por confiança operacional insuficiente; a decisão permaneceu HOLD, com zero ordens e sem credenciais. Evidência: `docs/reports/evidence/backend_sandbox_smoke_2026-11-19.json`.

Validação integral local final: **357 passed, 4 skipped, 1 warning**. O guia `docs/BACKEND_SANDBOX_GUIDE.md` define conectores/dados, segredo/licença e checklist verificável. O relatório `docs/reports/backend_provider_security_2026-11-19.md` registra os testes e o achado independente de egress corrigido. CI PostgreSQL/container e revisão da PR deste incremento são gates próprios; consultar a PR associada para o SHA e resultado vigentes.

**Ainda pendente:** demais callsites 9.3, ledger autoritativo 8B/C, cotas/custos distribuídos e entitlement, identidade/isolamento por cliente, auth WebSocket público sem token em query, testes manuais frontend/backend, Testnet/shadow prolongado e staging VPS com TLS, restart, restore PostgreSQL/Redis, alertas e runbook. Não houve publicação de servidor ou habilitação live. Os dois callers leaf de persistência de notícias/tendências migrados não encerram o inventário histórico de 59 callsites.

## Revisão corretiva da PR #33 antes do merge — 2026-11-19

A revisão automatizada apontou o P2 de providers Premium intencionalmente disabled degradando readiness. O fix separa enabled/state/ok, exclui apenas opt-out explícito da agregação e mantém erro de fonte habilitada/credencial ausente como unhealthy. O gate de entrada não conta disabled como fonte saudável. Validação integral do fix e do gerador de progresso: **368 passed, 4 skipped, 1 warning**; CI do novo head deve ser verificado antes do merge autorizado.

Status por checklist antes do merge: **6/16 gates aceitos, 37,5%**, com denominador e hash versionados em `docs/progress/pr33_readiness_fix_before_merge_2026-11-19.json`. Esse percentual é de aceites do checklist, não código completo, segurança certificada, lucro ou autorização de negociação. `scripts/backend_progress_status.py` registra cada incremento sem inflar o indicador por corrigir um gate já aceito. Relatório corretivo: `docs/reports/pr33_readiness_fix_2026-11-19.md`.

## ZT01 — control-plane e fundação de escopo por cliente (2026-11-19)

PR33 integrada em 10168db, branch preservada e CI pós-merge verde. Nova branch ZT01 implementa diagnóstico real de flags/menu disable-only, veto de ordem/proteção/OCO, hook pré-dispatch POST signed/ID, kill local+persistência antes de await e restauração conservadora antes do adapter; autostart live não rearma em qualquer ambiente. Autonomia/Redis é reavaliada em engine/Sniper/OrderManager/confirm. Reuso de client_order_id com conta/parâmetros diferentes é conflito explícito, sem consulta/envio da ordem divergente.

A análise sob demanda fecha dados/notícias incompletos e declara execution_authorized=false; regime inválido retorna unknown/bad_data. Migration aditiva c3f1e2a9b7d4 cria quatro tabelas de tenant/principal/membership/conta, com FKs/constraints/roles e Scope por JOIN explícito. Não há auth/RLS/API multi-tenant completa ou ledger autoritativo. Nenhum dado legado foi atribuído por adivinhação a cliente/conta.

Suíte final após follow-up: **421 passed, 5 skipped, 1 warning**. As três reproduções da revisão independente foram fechadas para refinamento com defaults OFF; aceite operacional/Mainnet segue **não aprovado**. PG/CI do novo head é gate separado. Smoke público repetido: 119 candles fechados, 10 features, 86 linhas válidas, HOLD e zero ordens.

Progresso cumulativo baseline: **7/16, 43,75%**, não segurança/lucro/autorização. O novo PR tem checks/aceite próprios e não está automaticamente autorizado pelo merge anterior. Relatório detalhado e plano financeiro: `docs/reports/zt01_backend_control_plane_scope_2026-11-19.md`; snapshot `docs/progress/zt01_current_2026-11-19.json`; diagrama `docs/diagrams/zt01_trust_boundaries.mmd`/PNG.

Próximos gates: binding JWT/membership e repositories privados com RLS PostgreSQL; observer read-only idempotente default OFF e ponte class-aware; produtor financeiro autenticado/fills/fees/cursors/manifesta/closure independente; OOS/licenças/cotas; staging real com restore/alertas/incidentes. Getters verified permanecem None e live/manual/autonomia/autostart OFF.

## Cofre de credenciais KMS — implementação no Sandbox (2026-11-24)

Em branch independente `feature/gate-credential-vault`, baseada em `master` pós-PR #34 (`360073b`), foi implementado serviço interno tenant/conta para envelope AES-256-GCM com chave de dados do AWS KMS, autorização por `resolve_client_scope`, versionamento otimista, revogação local e auditoria metadata-only. Startup production/staging exige configuração KMS válida e cofre habilitado; defaults continuam OFF em desenvolvimento. Não foi implementado gateway de Exchange nem integração aos fluxos de ordem.

Validação do Sandbox: **436 passed, 5 skipped, 1 warning**; os cinco skips exigem PostgreSQL via `TEST_DATABASE_URL`. Testes focados: 35 passados; `compileall`, `uv pip check`, `git diff --check`, upgrade/downgrade Alembic em SQLite temporário e `alembic check` passaram. O adapter foi exercitado por `botocore.stub.Stubber`, não por AWS real. Relatório completo e limitações: `docs/reports/credential_vault_sandbox_2026-11-24.md`.

**Status: PARCIAL / NOT ACCEPTED.** Nenhuma chamada AWS KMS real, policy/role IAM, PostgreSQL local, CI deste incremento ou integração Demo/Testnet foi validada. A revisão estática destacou bloqueios antes de expor o serviço: `TrustedCaller` ainda não vem de uma fronteira JWT→`PrincipalV1`; o audit de acesso pode ser revertido depois de o segredo ser entregue; e restore de backup antigo pode ressuscitar envelope revogado. A migration `f72c4a8e1d90` e a migration Passkey `e8c4b70d2a91` são atualmente irmãs sob `c3f1e2a9b7d4`; preservar PR/branch Passkey #35 sem alterações e resolver a cadeia antes de integrar ambas. Não recalcular `7/16` nem avançar ao próximo gate até validação real e confirmação desta consolidação.

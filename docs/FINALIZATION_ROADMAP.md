# Plano de finalização — ZIA-TRADER v17, Fase 9 em andamento

**Atualizado:** 2026-11-03. **Base desta atualização documental:** `master` pós-PR #28, SHA `60e92a551f08dca6034ebb48059d7b2418186402`; documentação adicional em `docs/pr28-merge-evidence`. O objetivo segue sendo **pré-produção supervisionada em VPS**, não prometer capital real ou código sem defeitos.

## Onde estamos: pontuação de engenharia, não métrica estatística

Os percentuais abaixo são uma avaliação de gates/evidências, não uma contagem de linhas implementadas, probabilidade de lucro ou certificação de segurança. Foram atribuídos conforme itens verificados e bloqueios ainda abertos.

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

**Status:** implementação e validação local concluídas e PR [#30](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/30) aberto contra `master`. O primeiro CI encontrou fixture de backup com conflito antigo; correção enviada em `e1a105c16ffcbf302265695369c0fdb51216aff5`. CI run `41828549273`: **259 passed, 1 warning** com PostgreSQL; jobs `test` e `container` verdes. Após atualização documental, o run `41829059384` também passou ambos os jobs no SHA `e4ab9d75569b229ecc5be6cd3b77fc55161800c2`. CodeRabbit `SKIPPED`, sem revisão humana registrada. PR limpo/mergeable, mas merge ainda aguarda decisão humana. Os três testes PostgreSQL foram localmente ignorados por ausência de `TEST_DATABASE_URL`; o CI os executou. Persistência operacional fora do CI, deployment/VPS e revisão operacional de licenças não foram realizados. Próximos gates: aprovação das condições de uso dos datasets pretendidos, homologação de persistência read-only em staging e somente então expansão para o ledger 8B e dados licenciados/OOS 8C. `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, autonomia/manual/autostart continuam inalterados.

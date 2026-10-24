# Plano de finalização — ZIA-TRADER v17, Fase 9 em andamento

**Atualizado:** 2026-10-23. **Base:** `master` após PR #20 (`f39ae9711f68ba59882a196c72e7fd4f123aa205`); implementação local na branch `phase9/app-factory-and-router-boundaries`, ainda aguardando PR/CI. O objetivo é chegar a **pré-produção supervisionada em VPS**, não prometer capital real ou código sem defeitos.

## Onde estamos: pontuação de engenharia, não métrica estatística

Os percentuais abaixo são uma avaliação de gates/evidências, não uma contagem de linhas implementadas, probabilidade de lucro ou certificação de segurança. Foram atribuídos conforme itens verificados e bloqueios ainda abertos.

| Dimensão | Estimativa | Evidência e limitador dominante |
|---|---:|---|
| Arquitetura backend e controles de segurança | **75–80%** | Alembic/PostgreSQL, gates fail-closed, OrderManager, reconciliação, controles de risco, logs e regressões temporais existem; ledger financeiro verificável, SAST completo e revisão humana independente continuam pendentes. |
| Estrutura de engenharia e testes locais | **78–80%** | Fase 8A integrada; Fase 9.1 integrada; 9.2 implementada na branch com factory/routers, gate de configuração e regressões. 220 testes locais passaram; CI/PR 9.2 ainda pendente. |
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
- **9.2 — app factory, routers e gates (implementada localmente; PR/CI pendentes):** `main.py` reduzido a entrypoint de 12 linhas; 5 routers preservam 24 combinações de rota; runtime e tasks isolados por `app.state`; start/stop linearizados por lock comum; API e worker bloqueiam config production insegura antes de inicializar runtime; scanner AST limitado tem regressões no pytest, mas não é gate de segurança; `.dockerignore` exclui payloads privados/dados e preserva `data/news_processor.py`; CI ganhou smoke de import da imagem. Revisões independentes orientaram a correção da corrida e de falsos negativos SQL; outra detectou normalização inconsistente de `AUTH_MODE`, corrigida e coberta. Evidência local: `220 passed, 3 skipped, 1 warning`, `compileall`, `git diff --check`, `uv pip check` e YAML. Sem build/Compose local; sem CI/merge desta branch. Relatório: `docs/reports/phase9.2_codebase_map_2026-10-23.md`.
- **9.3 — persistência não bloqueante:** mapear operações ORM síncronas dentro de corrotinas; escolher SQLAlchemy async/repositórios por escopo, sem compartilhar `Session` entre threads/tasks; medir p95, cancelamento e saturação do pool.
- **9.4 — stream de mercado read-only:** implementar protocolo/adapter só depois da seleção de venue/fonte; cobertura obrigatória de gaps, sequência, heartbeat, reconexão, staleness e backpressure.
- **9.5 — execução em Demo/Testnet supervisionado:** ensaiar intent/idempotência, partial fill, timeout, restart e kill switch após gates de ledger/dataset; mainnet não é parte da Fase 9 inicial.
- **9.6 — LLM opcional e isolado:** não é requisito para core trader. Se houver caso de uso aprovado, restrito a sumarização read-only estruturada e sem caminho para `RiskAI`/`OrderManager`.

**Estado da Fase 9 como um todo:** em andamento; 9.1 está integrada; 9.2 foi implementada na branch e aguarda CI e merge; 9.3+ ainda abertas. Suíte local atual `220 passed, 3 skipped, 1 warning`; os skips locais são integrações que exigem `TEST_DATABASE_URL`. CI verde ou build de imagem não significa aprovação de produção, ledger, dataset ou VPS. Manter live/autonomia OFF.

## Próximo passo executável

Concluir revisão follow-up, CI/build e merge da 9.2; então iniciar 9.3 em alteração incremental e medida. Em paralelo, ledger 8B e requisitos de dados 8C continuam bloqueadores — não substituir fontes reais por fixtures como prova de mercado. Só depois de ledger/dataset e escolha explícita de ambiente avançar para staging. Manter `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, `AUTO_START_ENGINES=false`, `AUTONOMOUS_TRADING_ENABLED=false`, `MANUAL_TRADING_ENABLED=false`, `NEURAL_MODELS_ENABLED=false` e `BACKTEST_USE_ENSEMBLE=false`.

## Limites e decisões externas

Para avançar a testes de integração são necessários: definição do alvo VPS (arquitetura/OS), escolha de fornecedor autorizado de dados, e venue Demo/Testnet pretendida. Não são necessários para a resolução local 8A. Credenciais de live ou de carteiras não devem ser solicitadas nem usadas nesta etapa.

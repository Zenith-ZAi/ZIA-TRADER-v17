# Fase 9.2 — Mapa do código, hardening e estado de validação

**Data:** 2026-10-23. **Checkout:** `/home/ubuntu/ZIA-TRADER-v17-remote`. **Branch de trabalho:** `phase9/app-factory-and-router-boundaries`. **Estado nesta revisão:** alterações locais testadas; PR/CI/merge ainda pendentes. Este relatório descreve engenharia do repositório, não autoriza execução financeira.

## 1. Resumo executivo

A subfase 9.2 conclui a separação inicial da API FastAPI: `main.py` deixa de concentrar rotas e fica com 12 linhas como entrypoint de compatibilidade; `api/application.py` cria a aplicação e seu lifespan; cinco routers separam autenticação, health/metrics, operações, mercado e motores; `api/dependencies.py` resolve settings/runtime por `Request` e `app.state`. Os caminhos HTTP/WebSocket preservados foram comparados ao contrato anterior e cobertos por teste: **24 combinações método/caminho**, sem alteração intencional em payloads, roles ou gates de execução.

O segundo objetivo foi reforçar startup e concorrência. API e worker validam configuração de produção antes de abrir runtime, banco ou providers; valores de segredo/admin de exemplo, autenticação demo e flags de autonomia/live causam bloqueio. Start e stop agora compartilham o mesmo lock de lifecycle. O analisador AST de segurança foi corrigido para cobrir SQL interpolado inline e atribuído a nomes/aliases dentro do escopo analisado, recebeu regressões e foi conectado ao CI como triagem estática.

A suíte local fecha em **219 passed, 3 skipped, 1 warning**. Compilação, `git diff --check`, scanner AST, `uv pip check` e parsing YAML passaram. O Sandbox não dispõe de Docker/Compose/Podman; a imagem e o novo workflow ainda precisam passar no CI remoto. **Não há aprovação de VPS, ledger financeiro, dataset/modelo de procedência, homologação de venue nem autorização para trading.**

## 2. Path e dimensões do repositório

Contagem reproduzível do working tree por `git ls-files -co --exclude-standard`, excluindo `__pycache__`: **206 arquivos-fonte/configuração selecionados, 28.327 linhas físicas**. Composição: 193 arquivos Python/27.526 linhas; 7 scripts shell/155 linhas; 1 YAML/45 linhas; 5 arquivos YML/601 linhas. A contagem inclui comentários e linhas em branco e serve apenas como dimensão estrutural; não mede complexidade, cobertura, valor de trading ou prontidão operacional. O contador pode mudar com documentação/build manifests não incluídos nessa seleção.

Path de entrada e fronteiras relevantes:

- `main.py` → entrypoint ASGI compatível (`uvicorn main:app`) → `api/application.py` (`create_app`, lifespan, middleware e montagem dos routers).
- `api/routers/auth.py`, `health.py`, `operations.py`, `market.py`, `engines.py` → 5 grupos de rotas; `api/dependencies.py` resolve settings e runtime por aplicação.
- `api/application_runtime.py` → ownership do runtime e do shutdown; migrations continuam fora do event loop conforme 9.1.
- `api/runtime_services.py` → status, reconciliação, start/stop, registry de tasks e lock compartilhado por app.
- `worker.py` → processo separado; os engines só podem iniciar sob flags/gates/reconciliação.
- Core de decisão/risco/ordens permanece em `core/`, `risk/` e `execution/`; esta subfase não altera indicadores, sinal, thresholds, sizing nem algoritmo de ordens.

A prova de import frio permanece em `tests/test_application_factory.py`: importar `main` não carrega `core.manager` nem Torch e não cria runtime. A fábrica cria registries de tasks isolados por instância. Telemetria OpenTelemetry continua sendo process-global; configuração diferente depois da primeira inicialização gera aviso explícito e não troca o provider, limitação a considerar ao hospedar múltiplas apps/configurações no mesmo processo.

## 3. Banco de dados e operações de IA

A inspeção estática de `database.py` encontrou **28 tabelas ORM**, incluindo:

- **Ordens/estado e auditoria:** `account_state`, `positions`, `runtime_position_state`, `order_history`, `execution_history`, `trades`, `order_intents`, `reconciliation_snapshots`, `protection_orders`, `kill_switch_events`, `audit_log`.
- **Risco e relatórios:** `daily_pnl`, `weekly_pnl`, `monthly_pnl`, `drawdowns`, `backtest_runs`, `decision_snapshots`.
- **Dados/IA/MLOps:** `ai_observations`, `market_patterns`, `model_registry`, `model_metrics`, `market_candles`, `trend_snapshots`, `news_articles`, `order_book_snapshots`, `data_gaps`, `whale_activity`.
- **Operação:** `system_logs`.

Alembic lista uma migração inicial (`8d429f0ec081`) e a revisão head (`b7d2d043ee8a`, bounded order-book history). Essa existência de registry, P&L agregado e snapshots **não equivale a um ledger financeiro verificável**: continuam ausentes `equity_ledger_v1` e `closed_execution_ledger_v1`; `DatabaseManager` permanece fail-closed nesses contratos.

Não há pesos `*.pt`, `*.pth` ou `*.onnx` rastreados nem dataset OHLCV de procedência/licença validada no conjunto versionado. Há JSONs de resultado/eventos de protocolo, que não são evidência de dataset de produção. Existe um SQLite local ignorado pelo Git (`data/zia_trader.db`, 331.776 bytes na inspeção de metadados); seu conteúdo **não foi consultado** nem contado como ledger ou dataset. O build context exclui os dados locais sob `data/` e permite somente o código runtime `data/news_processor.py`.

## 4. Scripts e tarefas programadas

Há **43 arquivos** em `scripts/` (Python e shell), organizáveis por função: ingestão/manifesto de mercado e notícias; treino/labels/replay/backtest/calibração; auditoria de lógica/API/runtime/segurança; inicialização/otimização/backup/restore de banco; preflight, TLS e firewall; benchmark e perfis. O inventário exato está em `scripts/` no checkout acima.

O Compose local tem 4 serviços (`db`, `redis`, `api`, `worker`). O Compose VPS define 11 serviços: esses quatro mais `db-init`, `market-snapshot-collector`, `model-drift-monitor`, `monthly-backtest`, `nginx`, `prometheus` e `news-ingest`. Coleta, drift, jobs, proxy e observabilidade são ativados por profiles; por padrão não se deve inferir que estão todos ativos. Coletor de snapshots e monitor de drift são processos de loop com intervalo; backtest mensal e ingestão de notícias são comandos de job, não um scheduler de calendário interno. Não foi encontrado APScheduler/cron controlando as tarefas do core. O usuário/operador ainda precisa provisionar dados rotulados e ativar profiles intencionalmente.

## 5. Alterações de segurança e build

`config/startup_validation.py` valida em `production`/`prod`/`staging` e é chamado no lifespan da API, no começo do worker e no `scripts/vps_preflight.py`. O startup bloqueia segredo JWT padrão/placeholder ou abaixo de 32 bytes, demo-auth, `AUTH_MODE` diferente de `env`, usuário/password ausente ou password placeholder/abaixo de 16 bytes, flags `AUTO_START_ENGINES`, live, autonomia, manual ou neural ligadas, kill switch desligado, shadow desligado, ausência de PostgreSQL/Redis persistentes, ausência do gate Alembic ou `BINANCE_MODE=live/mainnet`. O erro não escreve o valor dos segredos em logs. O template `.env.vps.example` deliberadamente contém placeholders e deve falhar até ser preenchido com segredos reais gerados fora do Git.

A revisão encontrou uma corrida em que um stop poderia cruzar um start ainda em reconciliação. `start_engine` e `stop_engines` agora se linearizam pelo mesmo lock, e um teste controlado por eventos confirma que o stop aguarda e cancela a task criada antes de retornar.

O antigo scanner `scripts/security_audit.py` baseava SQLi em busca textual e gerava falso positivo/falso negativo. Foi substituído por triagem AST de `execute`/`exec_driver_sql`, f-string, `%`, `.format`, composição, aliases/atributos locais, `AugAssign` e argumento nomeado `statement`/`sql`; reconhece prefixos/comandos como `TRUNCATE`, `MERGE` e `WITH`; avalia também `eval`, `exec` e `os.system`. O fixture de migration SQLite deixou de interpolar identificadores SQL e usa metadata SQLAlchemy. `tests/test_security_audit.py` cobre SQL parametrizado seguro, SQL interpolado inline/local/composto, em atributo, por keyword, AugAssign, alguns comandos e primitives dinâmicos. A CLI do scanner é **informativa, não é gate de segurança do CI**; o CI executa somente suas regressões como parte do pytest, e a imagem recebe smoke funcional de imports. Essa decisão evita apresentar a heurística como SAST. **Limite declarado:** não é SAST/DAST completo, não acompanha fluxo arbitrário entre funções/retornos, SQL montado dinamicamente por helpers ou fontes externas; zero achados quer dizer somente que os padrões implementados não encontraram uma ocorrência.

`.dockerignore` exclui `.env` e `.env.*` recursivos, chaves/certificados, payloads/datasets locais sob `data/`, modelos, relatórios, documentação, testes, caches e artefatos, mas mantém o módulo runtime `data/news_processor.py`. Essa exceção é necessária: core e job de notícias importam esse módulo. Um teste verifica a allowlist e uma nova etapa CI fará `docker run` da imagem construída para importar `NewsProcessor` e `scripts.ingest_news`; essa execução no container ainda aguarda CI. Nenhum arquivo secreto foi copiado, inspecionado ou publicado nesta etapa.

## 6. Evidências reproduzidas

- `python -m pytest -q -rs`: **220 passed, 3 skipped, 1 warning**, em 20,31 s no venv limpo de Python 3.12 sincronizado pelo lock CPU.
- Os 3 skips locais declaram ausência de `TEST_DATABASE_URL`: migration PostgreSQL (`tests/test_database_migrations.py:129`), integração do model registry (`tests/test_model_registry.py:107`) e backup/restore PostgreSQL (`tests/test_postgres_backup_restore.py:48`). O serviço PostgreSQL é exercitado no workflow CI, mas CI desta branch ainda estava pendente no instante de escrita.
- Warning único: `PendingDeprecationWarning` de Starlette/form parser sugerindo `python_multipart`; não foi convertido em falha de teste.
- Conjunto focado anterior de API/factory, segurança AST, startup settings e preflight: **39 passed, 1 warning**; foi acrescentado mais um teste de normalização AUTH_MODE, incluído na suíte integral final.
- `python -m compileall -q .`: exit 0; `git diff --check`: exit 0; `uv pip check` no venv limpo: 117 pacotes compatíveis, exit 0.
- Triagem AST local: sem ocorrências segundo os padrões limitados implementados; os casos suportados são exercitados por unit tests. `docker-compose.yml`, `docker-compose.vps.yml` e CI passaram por parser YAML. O CI contém smoke de import da imagem, ainda pendente nesta branch.
- Docker, Docker Compose e Podman não estão instalados/acessíveis na Sandbox. Não foram executados build ou up local, serviços PostgreSQL/Redis externos, exchange, transação, backup/restore real, TLS, firewall ou VPS. O build do container e o smoke `docker run` de imports/runtime, além dos testes no PostgreSQL, aguardam CI remoto.

## 7. Revisão independente e limitações

Revisões arquiteturais independentes confirmaram preservação dos 24 métodos/caminhos, roles e gates de order submission, e encontraram: (P1) corrida start/stop; (P2) falsos negativos SQL em variável, composição, atributo, keyword, `AugAssign` e verbos pouco comuns; (P2) normalização inconsistente de `AUTH_MODE`; (P3) configuração OTEL process-global. P1 recebeu lock compartilhado e regressão de concorrência; os casos P2 de scanner encontrados receberam propagação intra-scope, allowlist mais ampla de palavras SQL e regressões dedicadas; o scanner permaneceu fora do gate de segurança CI por não ser análise abrangente. A divergência de `AUTH_MODE` foi corrigida por normalização consistente e teste de regressão dentro da suíte integral. P3 emite aviso quando configurações OTEL diferem. O último parecer encontrou apenas a divergência de `AUTH_MODE`; os patches posteriores foram testados localmente, mas não houve novo parecer independente depois deles.

Permanecem limitações estruturais: chamadas síncronas de SQLAlchemy e partes CPU-bound Pandas/NumPy/Torch ainda podem bloquear corrotinas; rate limit em memória não é distribuído entre processos; não há feed WebSocket de mercado homologado; registry/drift não substituem dataset/modelo aprovado; a execução segue impedida por ledger incompleto. Esses itens são próximos trabalhos, não assumidos como resolvidos nesta subfase.

## 8. Próximas etapas priorizadas

1. Fechar revisão follow-up, CI PostgreSQL, testes do scanner como parte de pytest, build e smoke de imports da imagem no PR 9.2; resolver findings antes de merge. O CI verde não substitui revisão manual nem VPS.
2. **Fase 9.3:** decidir por SQLAlchemy async ou repositórios com fronteira explícita; remover I/O sync de corrotinas, nunca compartilhar `Session` entre tasks/threads; medir latência p50/p95/p99, cancelamento, saturação de pool e cleanup sob falha.
3. **Fase 8B (bloqueador financeiro):** especificar e implementar ledgers imutáveis com `Decimal`, idempotência, fills parciais, fees, funding, depósitos/saques, timestamps UTC, completude e reconciliação; continuar rejeitando entrada até proveniência demonstrada.
4. **Fase 8C (bloqueador de validação de IA):** escolher fonte/licença, coletar dataset identificado por instrumento/timeframe/hash, validar timezone/gaps/labels, executar walk-forward OOS com custos e revisão humana; não fabricar modelo aprovado.
5. **Fase 9.4/8D:** somente após selecionar feed/venue e ambiente, criar stream read-only com sequência/gaps/heartbeat/backpressure e validar deploy em staging isolado com Compose, migrations, volumes, proxy/TLS, backup/restore e restart.
6. **Fases 9.5/8E–8F:** Demo/Testnet, soak supervisionado e qualquer decisão de live apenas depois dos gates; live permanece OFF e não é ativado por merge.

**Decisão:** 9.2 é implementação de estrutura e controles, não fechamento do produto. Hoje o sistema ainda não está pronto para trading autônomo, VPS operacional 24/7 ou capital real.

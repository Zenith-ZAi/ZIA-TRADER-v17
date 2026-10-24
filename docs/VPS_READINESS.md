# Avaliação de prontidão para VPS — ZIA-TRADER v17

**Atualizado:** 2026-10-21. **Resultado:** **NÃO APROVADO para deployment verificado nem negociação autônoma.** Preparação estrutural parcial; esta branch trata a portabilidade de dependências, mas não habilita ordens, não valida rentabilidade e não substitui homologação independente.

## Evidência implementada/verificada

- Python 3.12.3 na Sandbox ARM64; suíte integral Phase 8A no venv limpo: **192 passed, 3 skipped, 1 warning** (Starlette/PendingDeprecation; 20,47 s). O baseline Phase 7 continha 189 testes.
- Um ambiente descartável Python 3.12 ARM64 foi sincronizado pelo novo `requirements.lock` via UV com backend CPU: 117 pacotes, `uv pip check` exit 0, Torch `2.13.0+cpu`, sem `cuda` e sem `nvidia-cusparselt-cu13`; os mesmos 189 testes passaram (32,84 s).
- Resolução cruzada `x86_64-unknown-linux-gnu` também seleciona Torch CPU e não gera dependências CUDA/NVIDIA/Triton.
- Novo teste do lock: 3 passed. O ambiente/venv anterior permanece intocado e ainda registra o wheel incompatível; reinstalação controlada pelo lock é o caminho corrigido.
- CI do PR #20 (run `39651671722`, SHA `e375072658cad0e581ac75cbfbd4cf27aa5f78f0`): jobs `test` e `container` passaram; o runner GitHub construiu a imagem. CodeRabbit foi marcado como revisão ignorada; não houve revisão manual registrada.
- Os Compose da Fase 7 foram validados estaticamente anteriormente: `db-init` aplica Alembic, preflight exige revisão, flags trading/autostart permanecem OFF, API fica em loopback e API/worker usam hardening. Isso não é execução de container.
- Não houve broker/exchange, envio de ordem, uso de capital, deploy, nem acesso a VPS.

## Não verificado

- O Sandbox não tem Docker CLI/Compose, Podman ou daemon acessível. Não foram executados `docker compose config`, Compose up, health check em container, teste de rede/volume, shutdown/restart nem smoke do Compose. O build da imagem no CI não substitui esses ensaios.
- Não há PostgreSQL/Redis de VPS nesta sessão. Migrations foram exercitadas em SQLite local; a integração com PostgreSQL desta branch deve ser verificada pelo CI e depois em staging.
- Não foram instalados/validados certificados TLS, domínio, Nginx em execução, firewall/UFW, SSH, NTP, alertas 24/7, limites CPU/RAM/IO, backup periódico ou restauração em banco limpo.
- Lock CPU prova compatibilidade na Sandbox ARM64 e resolução x86_64, mas não mede latência nem capacidade do Torch no hardware da VPS. A base Docker, Postgres e Redis continuam sem digest imutável; scanner CVE/SBOM/licenças não executado.
- Saúde, persistência, segredos do operador e falhas/restart com serviços externos ainda não foram testados.

## Gates bloqueantes antes de qualquer ativação

1. **Manter flags reais desligadas:** `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, `AUTO_START_ENGINES=false`, `AUTONOMOUS_TRADING_ENABLED=false`, `MANUAL_TRADING_ENABLED=false`, `NEURAL_MODELS_ENABLED=false` e `BACKTEST_USE_ENSEMBLE=false`. `BINANCE_MODE` inicia em `simulated`.
2. **Ledger de risco:** implementar e auditar `equity_ledger_v1` para períodos UTC completos diário/semanal/mensal e `closed_execution_ledger_v1` para Kelly; cobrir fees, funding, cashflows, fills duplicados/atrasados, reconciliação, restart e concorrência. Até aprovação, novas entradas permanecem corretamente bloqueadas.
3. **Dataset/modelo:** registrar origem e licença, instrumentos/timeframes, timezone, política de ajustes/gaps e SHA-256; validar labels maduros/custos; executar walk-forward/OOS e revisão humana. Não criar/ativar artefato fictício.
4. **Aprovar dependências/build:** receber CI verde de teste e build desta branch; build/scan limpo em runner alvo; definir política de atualização da base, lock, CVEs e artefatos.
5. **Staging isolado ponta a ponta:** executar `docker compose config`/build; subir DB/Redis; aplicar `db-init`/Alembic; confirmar revision/head e preflight; subir API/worker; validar health, persistência, reinício, logs e portas. Nenhum capital real.
6. **Hardening operacional:** gerar segredos fora do Git e proteger permissões/secret store; TLS, firewall/SSH/domínio, NTP, CORS/auth; testar alertas e kill switch.
7. **Backup/restore:** restaurar em ambiente independente, verificar checksums e contagens de dados críticos, intents/fills/snapshots; testar rollback de migration.
8. **Shadow/Demo/Testnet supervisionado:** só depois dos gates anteriores, com venue não live selecionada e validada. Ensaiar fill parcial, timeout ambíguo, reconciliação, rate-limit, OCO e restart, com supervisão humana. Este documento não autoriza mainnet.
9. **Soak e aceite independente:** janela contínua acordada, revisão de drift/alertas/atrasos/disco, backups e rollback; revisão de segurança/privacidade e aprovação humana explícita separada.

## Decisão operacional

O repositório está **preparado para seguir a validação controlada**, não para ser chamado “VPS-ready” em sentido operacional. A resolução de dependências CPU avança a preparação do build, mas não substitui CI nem container real. Ledger e dataset/modelo ainda bloqueiam entradas; staging, TLS, firewall, backup/restore, monitoramento e soak bloqueiam o aceite operacional. A pontuação e as etapas estão em `docs/FINALIZATION_ROADMAP.md`; confira também `docs/VPS_DEPLOYMENT_RUNBOOK.md`, `docs/DEPENDENCY_AUDIT.md`, `docs/INFRASTRUCTURE_AUDIT.md` e `docs/PHASE_COMPLETION_MATRIX.md`.


## Adendo de 2026-10-23 — Fase 9.2 local (não é aceite VPS)

A branch da Fase 9.2 adiciona app factory/routers e uma validação central de configuração de produção chamada antes do runtime da API, do worker e pelo preflight. Ela rejeita placeholders/segredos JWT fracos, demo-auth, credenciais admin incompletas, flags de execução live/autônoma/manual/neural/autostart ligadas, kill switch/shadow incorretos, ausência de PostgreSQL/Redis persistentes, ausência de exigência Alembic head e modo Binance live/mainnet. Foram adicionadas regressões para falha antes da construção do runtime e para não expor segredos em mensagens. Essas são garantias exercitadas em teste local; não provam que um arquivo `.env.vps` real está gerado, protegido ou carregado corretamente no servidor.

A evidência local final nesta branch é **220 passed, 3 skipped, 1 warning** após os últimos patches do scanner AST, build context e normalização do auth gate. Os skips locais dependem do serviço PostgreSQL via `TEST_DATABASE_URL`. `compileall`, `git diff --check`, `uv pip check` no venv limpo, testes unitários de padrões AST e parser YAML passaram localmente. A CLI heurística do scanner não é um gate de segurança do CI nem substitui SAST/DAST. O parser YAML não executa substituição Compose nem substitui `docker compose config`.

Docker CLI, Compose e Podman permanecem indisponíveis nesta Sandbox. **Não** houve build local, Compose up, smoke em container, execução do PostgreSQL/Redis VPS, teste de volumes, preflight contra serviço persistente, TLS, firewall, backup/restore ou soak. CI remoto desta branch ainda é gate antes do merge; o workflow agora inclui `docker run` de smoke para importar `data.news_processor` e o job de notícias dentro da imagem construída.

O status de deployment permanece **NÃO APROVADO**: não há ledger financeiro verificável (`equity_ledger_v1`/`closed_execution_ledger_v1`), dataset/modelo aprovado nem homologação externa. Um SQLite local ignorado pelo Git foi identificado somente por metadados e não consultado; não é prova de integridade ou proveniência e está excluído do build context. Do diretório `data/`, o build context mantém somente o código runtime `data/news_processor.py`, usado pelo core e pelo job de notícias; payloads e JSONs locais continuam excluídos. Todas as flags live e autonomia permanecem OFF. Ver o mapa detalhado em `docs/reports/phase9.2_codebase_map_2026-10-23.md`.

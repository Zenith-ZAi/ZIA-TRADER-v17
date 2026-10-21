# Avaliação de prontidão para VPS — ZIA-TRADER v17

**Data:** 2026-10-21. **Resultado:** **NÃO APROVADO como deployment verificado; preparação estrutural parcial.** Esta avaliação não habilita trading, não valida rentabilidade e não substitui homologação independente.

## O que foi verificado nesta rodada

- Python 3.12.3 na virtualenv `/home/ubuntu/.venvs/zia-v17`.
- `pytest -q`: **189 passed, 3 skipped, 1 warning**. O aviso é `PendingDeprecationWarning` de Starlette recomendando `python_multipart`.
- `python -m compileall -q .`: exit 0; `git diff --check`: exit 0.
- Os arquivos `docker-compose.yml` e `docker-compose.vps.yml` foram carregados com PyYAML 6.0.3. A checagem estática encontrou os serviços esperados, `db-init` usando `alembic upgrade head`, flags live/autostart false, API vinculada a `127.0.0.1` e hardening `read_only`/`cap_drop` na API e worker.
- Testes unitários das migrations e do preflight aprovam a revisão Alembic presente e bloqueiam schema sem `alembic_version` quando `REQUIRE_ALEMBIC_HEAD=true`.
- Não houve conexão a broker/exchange, envio de ordem, uso de capital, deploy, nem acesso a VPS.

## O que não foi verificado

- O Sandbox não tem Docker CLI/Compose, Podman ou daemon acessível. Logo, **não** foram executados `docker compose config`, build da imagem, `up`, health check de container, network/volume test, shutdown/restart ou smoke do Compose.
- Não há PostgreSQL/Redis de VPS nesta sessão. As migrations foram exercitadas em SQLite local; o serviço CI do projeto configura PostgreSQL 16, mas os resultados da branch-base não substituem CI do código atual.
- Não foram instalados/validados certificados TLS, domínio, Nginx em execução, firewall/UFW, SSH, sincronização de relógio, alertas 24/7, limites CPU/RAM/IO, backup periódico nem restauração em banco limpo.
- Não foi validado o `pip install` do Dockerfile em ambiente limpo. `uv pip check --python /home/ubuntu/.venvs/zia-v17/bin/python` retornou exit 1 por `nvidia-cusparselt-cu13` compilado para plataforma diferente. O Dockerfile instala `requirements.txt`, enquanto o lock não é aplicado pelo build; as dependências precisam de resolução/build reprodutível antes do aceite.
- O status de saúde e persistência com serviços externos, certificados reais e segredos definidos pelo operador não foi testado.

## Gates bloqueantes antes de qualquer ativação

1. **Não ativar flags reais:** manter `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, `AUTO_START_ENGINES=false`, `AUTONOMOUS_TRADING_ENABLED=false`, `MANUAL_TRADING_ENABLED=false`, `NEURAL_MODELS_ENABLED=false` e `BACKTEST_USE_ENSEMBLE=false`. O `BINANCE_MODE` inicial é `simulated`.
2. **Resolver ledger de risco:** implementar e auditar `equity_ledger_v1` para períodos UTC completos diário/semanal/mensal e `closed_execution_ledger_v1` para Kelly; testar fees, funding, fluxos externos, fills duplicados/atrasados, reconciliação e limites. Até lá, novas entradas continuam bloqueadas corretamente.
3. **Obter dataset confiável:** registrar origem, instrumento, timeframe, timezone, política de ajustes/gaps e SHA-256; validar labels maduros e custos. Só então executar walk-forward/OOS e revisão humana; não criar ou ativar artefato fictício.
4. **Corrigir e reproduzir dependências:** limpar incompatibilidade de pacote, definir política de pin/lock que o Docker build realmente consuma e construir a imagem em CI/runner compatível com produção.
5. **Validar Compose de ponta a ponta em staging isolado:** `docker compose config`; build; subir apenas DB/Redis; executar `db-init`/`alembic upgrade head`; confirmar preflight com revisão exata; subir API/worker; checar saúde, persistência, reinício e logs. Confirmar que API está só em loopback e DB/Redis sem portas publicadas.
6. **Hardening operacional:** gerar segredos novos fora do Git e restringir arquivo/secret store; instalar certificados válidos com chave protegida; configurar firewall/SSH/domínio; confirmar NTP; revisar CORS e autenticação; testar alertas e procedimento do kill switch.
7. **Backup e restore:** fazer backup e restauração em ambiente separado, validar checksums e contagens de tabelas críticas/intents/fills/snapshots antes de tratar backups como confiáveis.
8. **Homologação Demo/Testnet:** apenas após gates anteriores e mediante validação explícita isolada, cobrir fills parciais, timeout ambíguo, reconciliação, rate-limit, OCO e restart. Nenhuma mainnet está autorizada por este documento.

## Decisão operacional

O repositório está **preparado para continuar validação controlada em ambiente isolado**, não para ser chamado “VPS-ready” em sentido de implantação comprovada. É possível planejar uma execução de staging com todas as flags de trading desligadas depois de um build limpo e do teste real do Compose. Os bloqueios de ledger e dataset impedem declarar entradas de trading autorizadas ou modelo validado; TLS, firewall, backup/restore e serviços persistentes impedem declarar homologação de VPS concluída.

Consulte também `docs/VPS_DEPLOYMENT_RUNBOOK.md`, `docs/DEPENDENCY_AUDIT.md`, `docs/INFRASTRUCTURE_AUDIT.md` e `docs/PHASE_COMPLETION_MATRIX.md`.

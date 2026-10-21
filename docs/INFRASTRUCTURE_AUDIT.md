# Auditoria de infraestrutura e configuração

**Data:** 2026-10-21. **Resultado:** configuração estrutural revisada; Docker/Compose e VPS **não executados**.

## Inventário relevante

- `Dockerfile`: base `python:3.12-slim`, instala `requirements.txt`, copia aplicação, cria usuário `nonroot` e executa sem privilégios.
- `docker-compose.vps.yml`: PostgreSQL 16, Redis 7 com AOF/senha, `db-init`, API, worker, perfis opcionais de coleta, drift, jobs, proxy Nginx e Prometheus; volumes nomeados para estado.
- `scripts/vps_preflight.py`: verifica flags, DB, Redis, tabelas, persistência, arquivos de alertas, TLS opcional e diretórios graváveis.
- `migrations/env.py` consome `DATABASE_URL`; `DatabaseManager.create_tables()` em PostgreSQL delega a `alembic upgrade head` com advisory lock. Nesta branch, o serviço inicial `db-init` executa explicitamente `alembic upgrade head`; API e worker dependem da conclusão.
- O preflight estrito recebe `REQUIRE_ALEMBIC_HEAD=true`, lê `alembic_version`, compara a revisão corrente com os heads do repositório e não altera schema.

## Validação executada

1. `docker --version`, `docker compose version`, `podman`, `docker-compose` e `yq`: binários não encontrados no Sandbox.
2. Parser estático: PyYAML 6.0.3 carregou `docker-compose.yml` e `docker-compose.vps.yml`; ambos têm mapa de serviços coerente. Resultado: YAML válido.
3. Invariantes estáticos da configuração VPS: `db-init.command == ["alembic", "upgrade", "head"]`; API/worker têm live, modo live e autostart false, `REQUIRE_ALEMBIC_HEAD=true`, root filesystem read-only e `cap_drop: ALL`; API está publicada em `127.0.0.1`.
4. Testes `tests/test_vps_preparation.py` e `tests/test_database_migrations.py`: 8 passed, 1 skipped. Cobrem head Alembic presente/ausente em SQLite de teste e migrations locais. O caso PostgreSQL depende de `TEST_DATABASE_URL` e foi skipped localmente.
5. `docs/VPS_DEPLOYMENT_RUNBOOK.md` foi alinhado para executar `db-init` antes do preflight estrito.

Essas verificações **não provam** que Compose aceita interpolation/merge no Docker instalado no VPS, que a imagem constrói, que os health checks dos containers ficam verdes ou que as migrations funcionam na versão exata de PostgreSQL do alvo.

## Grafo de inicialização esperado

```text
PostgreSQL healthy ──> db-init (alembic upgrade head) ──> API
Redis healthy ─────────────────────────────────────────> API / worker
PostgreSQL healthy ──> db-init (alembic upgrade head) ──> worker
```

API expõe a porta do container somente em loopback; PostgreSQL e Redis não têm `ports` publicados no Compose VPS. Nginx é perfil opt-in (`proxy`) e monta `deploy/tls/fullchain.pem`/`privkey.pem`; `REQUIRE_TLS_PROXY` e `FIREWALL_PREFLIGHT_REQUIRED` vêm false no template, portanto TLS/firewall ainda exigem configuração e validação operacional explícitas.

## Gaps de configuração/aceite

- Não há limites explícitos de CPU/memória configurados para os serviços. Não dimensionar VPS sem medir build, I/O e jobs com carga representativa.
- Imagens de serviços usam tags versionadas em alguns casos, mas não digest imutável. `python:3.12-slim` e dependências instaladas por `requirements.txt` podem variar com o tempo.
- Segredos são passados por `.env.vps`/variáveis de ambiente, não por Docker secrets ou secret manager nesta configuração. Manter arquivo fora do Git, com permissão restrita e segredos únicos gerados em hex para evitar caracteres especiais em DSN.
- Não existe evidência nesta sessão de certificado TLS real, firewall/UFW, NTP, alerta operacional, Prometheus ativo, restore PostgreSQL nem backup Redis restaurado.
- A incompatibilidade reportada por `uv pip check` e a ausência de Docker impedem aceitar a imagem como reproduzível.
- O ledger verificável para P&L/Kelly e o dataset de procedência verificada são bloqueios de trading/modelo independentes do Compose.

## Conclusão

Status **parcial, somente estático**. Execute o runbook em staging isolado com Docker e PostgreSQL/Redis compatíveis, faça build limpo, valide `docker compose config`, migrations, health/readiness, reinício, logs e restore. Não publique API diretamente na Internet e mantenha todas as flags de trading desligadas.

# Auditoria de infraestrutura e configuração

**Atualizado:** 2026-11-19. O inventário inicial abaixo registra a auditoria de 2026-10-21; build e testes PostgreSQL de CI posteriores constam nos adendos. O hardening da PR #32 foi integrado. O incremento atual valida egress/credenciais e coleta pública no sandbox, não staging VPS/Compose ou restore Redis real.

## Inventário histórico de 2026-10-21

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

## Adendo — hardening do backup Redis (2026-11-10)

`scripts/vps_backup.sh` agora aguarda a conclusão bem-sucedida de `BGSAVE`, copia o `/data/dump.rdb` do container Redis, rejeita snapshot vazio e calcula SHA-256 para todos os arquivos copiados. A senha é fornecida ao `redis-cli` via `REDISCLI_AUTH`, não pelo argumento `-a`. Os testes `tests/test_vps_backup.py` usam um comando Docker fake e verificam cópia, checksum e falha fail-closed; não houve chamada a Docker real, Redis, PostgreSQL ou VPS. O restore do RDB e consistência conjunta Redis/PostgreSQL continuam pendentes. Ver `docs/reports/phase9_architecture_hardening_2026-11-10.md`.


### Errata do follow-up independente — 2026-11-10

A revisão independente inicial encontrou dois P2 (hostname TLS e timeout de comandos); o follow-up encontrou que a configuração não chegava ao container API e que checar chave privada exigiria montá-la ali. Foram corrigidos: Compose encaminha apenas as três configurações TLS não secretas; o preflight usa hostname/SNI da URL, conecta ao DNS interno `nginx:443` e verifica handshake CA/hostname sem ler/montar a chave no API. GNU `timeout` envolve cada chamada Docker; testes bloqueiam dump, snapshot e cópias. Suíte local: **310 passed, 4 skipped, 1 warning**. CI `42836399864` no SHA `4893d18` passou com **314 passed, 1 warning** em PostgreSQL 16 e build/smoke do container; incompatibilidade inicial foi resolvida fixando o cliente em 16. PR #32 está aberta sem revisão humana registrada, e CodeRabbit foi ignorado. Certificado público, restore Redis/VPS e staging continuam pendentes; nenhum runtime de produção foi iniciado.


## Egress e credenciais do backend — 2026-11-19

O incremento remove herança implícita de HTTP_PROXY/HTTPS_PROXY/ALL_PROXY e CA de ambiente nos clients gerenciados de HTTP compartilhado, coletor unificado, smoke e Spot Testnet/Demo (trust_env=False). O transporte rejeita AsyncClient real injetado com herança habilitada; redirects continuam bloqueados. Um proxy HTTPS não lê payload dentro de TLS válido apenas por encaminhar CONNECT: a ameaça inclui desvio de tráfego e confiança de CA injetada. Proxy/CA legítimo exige configuração explícita e revisão de egress, não bypass por variável do ambiente.

.env, material .pem/.key e diretórios secrets/.secrets estão excluídos do Git e build Docker. Secret files são fonte nativa Pydantic opcional por _secrets_dir; não há mount automático de /run/secrets, KMS, rotação ou vault por cliente. Mount somente leitura e permissões devem ser assegurados no deployment. Nenhuma chave real foi inserida no checkout ou enviada ao repositório nesta rodada.

A validação real é de coleta pública Binance em SQLite isolado, 119 candles, reimportação idempotente e zero ordens. Ela não valida staging persistente, backup/restore VPS, Redis RDB real, TLS ou RPO/RTO. A PR #32 já foi integrada, portanto sua menção como aberta no adendo histórico acima não é o estado atual. O ledger segue audit-only. Suíte local final: **357 passed, 4 skipped, 1 warning**; CI do novo SHA deve ser consultado na PR associada. Limites: `docs/reports/backend_provider_security_2026-11-19.md` e `docs/BACKEND_SANDBOX_GUIDE.md`.


## ZT01 — latch/restart e escopo (2026-11-19)

PR33 integrada em 10168db e CI pós-merge verde. A nova branch restaura kill state limitado/determinístico por conta antes do adapter; estado ausente/falho/ativo fecha, e registro false não rearma live automaticamente. Ativação bloqueia localmente e persiste antes do await externo; autostart live é recusado também fora de production/staging. Hook final no transporte reduz a corrida reproduzida no worker legado; request já despachada não é atomicamente revogável na exchange e exige reconciliação/recuperação.

Migration aditiva c3f1e2a9b7d4 e quatro tabelas de identidade/escopo foram testadas em SQLite; o teste PG de constraints/cross-tenant roda somente com TEST_DATABASE_URL/CI. Não foram ativadas políticas RLS, roles de produção, vault por cliente, API multi-tenant, reverse proxy ou serviço VPS. Nenhuma credencial pertence aos modelos novos. 421 testes locais, 5 skips, um warning; não é homologação operacional. Restore Redis/TLS/Compose/soak e controle distribuído de incidente/rearm continuam pendentes. Detalhes: `docs/reports/zt01_backend_control_plane_scope_2026-11-19.md`.

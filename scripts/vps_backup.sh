#!/usr/bin/env bash
set -Eeuo pipefail

# Backup não destrutivo. Execute na raiz do repositório com o compose parado apenas
# se o operador quiser uma janela de consistência; pg_dump é consistente online.
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.vps.yml}"
ENV_FILE="${ENV_FILE:-.env.vps}"
BACKUP_ROOT="${BACKUP_ROOT:-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT}/${STAMP}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Arquivo de ambiente ausente: $ENV_FILE" >&2
  exit 1
fi
mkdir -p "$BACKUP_DIR"
umask 077

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${compose[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$BACKUP_DIR/postgres.dump"
"${compose[@]}" exec -T redis sh -c 'redis-cli --no-auth-warning -a "$REDIS_PASSWORD" bgsave' > "$BACKUP_DIR/redis_bgsave.txt"
"${compose[@]}" cp api:/app/data "$BACKUP_DIR/app_data"
"${compose[@]}" cp api:/app/models "$BACKUP_DIR/app_models"

sha256sum "$BACKUP_DIR/postgres.dump" > "$BACKUP_DIR/SHA256SUMS"
find "$BACKUP_DIR" -maxdepth 1 -type f -printf '%f\n' | sort > "$BACKUP_DIR/MANIFEST"
printf 'Backup concluído em %s\n' "$BACKUP_DIR"
printf 'Não inclui .env, chaves de API ou segredos. Teste de restauração deve ocorrer em projeto/volume separado.\n'

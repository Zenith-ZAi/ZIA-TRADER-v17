#!/usr/bin/env bash
set -Eeuo pipefail

# Backup não destrutivo. Execute na raiz do repositório com o compose parado apenas
# se o operador quiser uma janela de consistência; pg_dump é consistente online.
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.vps.yml}"
ENV_FILE="${ENV_FILE:-.env.vps}"
BACKUP_ROOT="${BACKUP_ROOT:-backups}"
BACKUP_COMMAND_TIMEOUT_SECONDS="${BACKUP_COMMAND_TIMEOUT_SECONDS:-600}"
BACKUP_REDIS_COMMAND_TIMEOUT_SECONDS="${BACKUP_REDIS_COMMAND_TIMEOUT_SECONDS:-75}"
REDIS_BGSAVE_MAX_ATTEMPTS="${REDIS_BGSAVE_MAX_ATTEMPTS:-60}"
REDIS_BGSAVE_POLL_INTERVAL_SECONDS="${REDIS_BGSAVE_POLL_INTERVAL_SECONDS:-1}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT}/${STAMP}"

for command_name in docker timeout; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Comando obrigatório ausente: $command_name" >&2
    exit 1
  fi
done

for setting_name in BACKUP_COMMAND_TIMEOUT_SECONDS BACKUP_REDIS_COMMAND_TIMEOUT_SECONDS REDIS_BGSAVE_MAX_ATTEMPTS; do
  setting_value="${!setting_name}"
  if [[ ! "$setting_value" =~ ^[1-9][0-9]*$ ]]; then
    echo "$setting_name deve ser um inteiro positivo" >&2
    exit 1
  fi
done
if [[ ! "$REDIS_BGSAVE_POLL_INTERVAL_SECONDS" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "REDIS_BGSAVE_POLL_INTERVAL_SECONDS deve ser um número não negativo" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Arquivo de ambiente ausente: $ENV_FILE" >&2
  exit 1
fi
umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
run_compose() {
  local description="$1"
  local timeout_seconds="$2"
  local status=0
  shift 2
  timeout --kill-after=5s "${timeout_seconds}s" "${compose[@]}" "$@" || status=$?
  if [[ "$status" -eq 124 || "$status" -eq 137 ]]; then
    echo "Timeout em $description após ${timeout_seconds}s" >&2
    return 1
  fi
  return "$status"
}

run_compose "dump PostgreSQL" "$BACKUP_COMMAND_TIMEOUT_SECONDS" \
  exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > "$BACKUP_DIR/postgres.dump"
run_compose "snapshot Redis" "$BACKUP_REDIS_COMMAND_TIMEOUT_SECONDS" \
  exec -T -e "REDIS_BGSAVE_MAX_ATTEMPTS=$REDIS_BGSAVE_MAX_ATTEMPTS" \
  -e "REDIS_BGSAVE_POLL_INTERVAL_SECONDS=$REDIS_BGSAVE_POLL_INTERVAL_SECONDS" redis sh -ec '
  export REDISCLI_AUTH="${REDIS_PASSWORD:?REDIS_PASSWORD ausente no container Redis}"
  max_attempts="${REDIS_BGSAVE_MAX_ATTEMPTS:?limite de polling Redis ausente}"
  poll_interval="${REDIS_BGSAVE_POLL_INTERVAL_SECONDS:?intervalo de polling Redis ausente}"
  before="$(redis-cli --no-auth-warning INFO persistence)" || { echo "Falha ao ler INFO Redis antes de BGSAVE" >&2; exit 1; }
  before_saves="$(printf "%s\n" "$before" | sed -n "s/^rdb_saves://p" | tr -d "\r")"
  case "$before_saves" in
    ""|*[!0-9]*) echo "Campo rdb_saves ausente/inválido antes de BGSAVE" >&2; exit 1 ;;
  esac
  redis-cli --no-auth-warning BGSAVE
  attempt=0
  while [ "$attempt" -lt "$max_attempts" ]; do
    if ! info="$(redis-cli --no-auth-warning INFO persistence)"; then
      echo "Falha ao ler INFO Redis durante BGSAVE" >&2
      exit 1
    fi
    in_progress="$(printf "%s\n" "$info" | sed -n "s/^rdb_bgsave_in_progress://p" | tr -d "\r")"
    saves="$(printf "%s\n" "$info" | sed -n "s/^rdb_saves://p" | tr -d "\r")"
    last_status="$(printf "%s\n" "$info" | sed -n "s/^rdb_last_bgsave_status://p" | tr -d "\r")"
    case "$in_progress" in 0|1) ;; *) echo "Campo rdb_bgsave_in_progress ausente/inválido" >&2; exit 1 ;; esac
    case "$saves" in
      ""|*[!0-9]*) echo "Campo rdb_saves ausente/inválido durante BGSAVE" >&2; exit 1 ;;
    esac
    if [ "$in_progress" = "0" ] && [ "$saves" -gt "$before_saves" ]; then
      [ "$last_status" = "ok" ] || { echo "Último BGSAVE Redis falhou: $last_status" >&2; exit 1; }
      echo "RDB concluído; rdb_saves=$saves; last_bgsave_status=$last_status"
      exit 0
    fi
    attempt=$((attempt + 1))
    if [ "$attempt" -lt "$max_attempts" ]; then sleep "$poll_interval"; fi
  done
  echo "Timeout aguardando incremento/conclusão de BGSAVE Redis após $max_attempts consultas" >&2
  exit 1
' > "$BACKUP_DIR/redis_bgsave.txt"
run_compose "cópia do RDB Redis" "$BACKUP_COMMAND_TIMEOUT_SECONDS" \
  cp redis:/data/dump.rdb "$BACKUP_DIR/redis_dump.rdb"
if [[ ! -s "$BACKUP_DIR/redis_dump.rdb" ]]; then
  echo "Snapshot Redis ausente ou vazio: $BACKUP_DIR/redis_dump.rdb" >&2
  exit 1
fi
run_compose "cópia dos dados da API" "$BACKUP_COMMAND_TIMEOUT_SECONDS" \
  cp api:/app/data "$BACKUP_DIR/app_data"
run_compose "cópia dos modelos da API" "$BACKUP_COMMAND_TIMEOUT_SECONDS" \
  cp api:/app/models "$BACKUP_DIR/app_models"

(
  cd "$BACKUP_DIR"
  find . -type f ! -name SHA256SUMS ! -name MANIFEST -print0 | sort -z | xargs -0 -r sha256sum > SHA256SUMS
  find . -type f ! -name MANIFEST -printf '%P\n' | sort > MANIFEST
)
printf 'Backup concluído em %s\n' "$BACKUP_DIR"
printf 'Não inclui .env, chaves de API ou segredos. Teste de restauração deve ocorrer em projeto/volume separado.\n'

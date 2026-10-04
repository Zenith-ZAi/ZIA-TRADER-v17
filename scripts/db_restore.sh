#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL deve apontar explicitamente para o banco de destino}"
BACKUP_FILE="${1:-}"
if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
  echo "Uso: DATABASE_URL=<destino> $0 <arquivo.dump>" >&2
  exit 2
fi
if [[ -f "$BACKUP_FILE.sha256" ]]; then
  sha256sum --check "$BACKUP_FILE.sha256"
fi

# Restauração substitui objetos com nomes iguais no banco-alvo; nunca use uma URL de produção sem janela aprovada.
pg_restore --dbname="$DATABASE_URL" --clean --if-exists --exit-on-error --no-owner --no-privileges "$BACKUP_FILE"
printf 'Restauração concluída em DATABASE_URL informado.\n'

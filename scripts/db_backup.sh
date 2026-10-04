#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL obrigatória}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$BACKUP_DIR/zia-${stamp}.dump"

pg_dump --dbname="$DATABASE_URL" --format=custom --compress=9 --no-owner --no-privileges --file="$backup_file"
sha256sum "$backup_file" > "$backup_file.sha256"
find "$BACKUP_DIR" -type f \( -name 'zia-*.dump' -o -name 'zia-*.dump.sha256' \) -mtime "+$BACKUP_RETENTION_DAYS" -delete
printf 'Backup criado: %s\n' "$backup_file"

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Credenciais devem vir do gerenciador de segredos do servidor ou de um .env local ignorado.
# Nenhuma chave é definida neste arquivo.
export PYTHONUNBUFFERED=1

MODE="${ZIA_MODE:-api}"
case "$MODE" in
  api)
    exec python3 main.py
    ;;
  worker)
    exec python3 worker.py
    ;;
  test)
    exec python3 -m pytest -q
    ;;
  *)
    echo "Uso: ZIA_MODE=api|worker|test $0" >&2
    exit 2
    ;;
esac

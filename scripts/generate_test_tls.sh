#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-deploy/tls}"
mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl é obrigatório para gerar o certificado de teste." >&2
  exit 1
fi

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$OUT_DIR/privkey.pem" \
  -out "$OUT_DIR/fullchain.pem" \
  -days 7 \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  >/dev/null 2>&1
chmod 600 "$OUT_DIR/privkey.pem" "$OUT_DIR/fullchain.pem"
echo "Certificado autoassinado de teste criado em $OUT_DIR; não use em produção."

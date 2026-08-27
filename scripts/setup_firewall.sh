#!/usr/bin/env bash
set -euo pipefail

# O padrão é apenas exibir as regras. Para aplicar, use FIREWALL_APPLY=true.
# Execute em console VPS com acesso out-of-band para evitar lockout acidental.
APPLY="${FIREWALL_APPLY:-false}"
SSH_PORT="${SSH_PORT:-22}"
HTTPS_PORT="${HTTPS_PORT:-443}"

run() {
  if [[ "$APPLY" == "true" ]]; then
    sudo "$@"
  else
    printf 'DRY-RUN:'
    printf ' %q' "$@"
    printf '\n'
  fi
}

if ! command -v iptables >/dev/null 2>&1; then
  echo "iptables não está instalado; configure o firewall do provedor ou instale-o antes de aplicar." >&2
  exit 1
fi

run iptables -F
run iptables -X
run iptables -P INPUT DROP
run iptables -P FORWARD DROP
run iptables -P OUTPUT ACCEPT
run iptables -A INPUT -i lo -j ACCEPT
run iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
run iptables -A INPUT -p tcp --dport "$SSH_PORT" -m conntrack --ctstate NEW -j ACCEPT
run iptables -A INPUT -p tcp --dport "$HTTPS_PORT" -m conntrack --ctstate NEW -j ACCEPT

if [[ "$APPLY" == "true" ]]; then
  if command -v netfilter-persistent >/dev/null 2>&1; then
    sudo netfilter-persistent save
  elif command -v iptables-save >/dev/null 2>&1; then
    sudo iptables-save | sudo tee /etc/iptables/rules.v4 >/dev/null
  fi
  echo "Firewall aplicado: somente SSH:${SSH_PORT} e HTTPS:${HTTPS_PORT} foram liberados na entrada."
else
  echo "Dry-run concluído. Nada foi alterado; defina FIREWALL_APPLY=true somente após confirmar console de recuperação."
fi

#!/bin/bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log()  { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
err()  { echo -e "${RED}❌ $1${NC}"; exit 1; }
info() { echo -e "${CYAN}ℹ️  $1${NC}"; }
step() { echo -e "\n${BLUE}══ $1 ══${NC}"; }

MODE="${1:-deploy}"

case "$MODE" in
  --logs)   docker-compose logs -f zia-app; exit 0 ;;
  --stop)   docker-compose down --remove-orphans && log "Sistema parado."; exit 0 ;;
  --status) docker-compose ps; exit 0 ;;
  --update)
    step "Atualizando ZIA TRADER v17"
    git pull origin main 2>/dev/null || git pull origin master 2>/dev/null || warn "Git pull falhou"
    docker-compose build --no-cache zia-app
    docker-compose up -d zia-app
    log "App atualizado."; docker-compose logs --tail=20 zia-app; exit 0 ;;
esac

echo -e "\n${GREEN}  ╔══════════════════════════════════════╗"
echo    "  ║   ZIA TRADER v17 — Deploy Script    ║"
echo -e "  ╚══════════════════════════════════════╝${NC}\n"

# ─── 1. Docker ───────────────────────────────────────────────────────────────
step "1/8 — Verificando Docker"
if ! command -v docker &>/dev/null; then
    warn "Docker não encontrado. Instalando..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    log "Docker instalado. Você pode precisar reconectar ao SSH."
else
    log "Docker: $(docker --version)"
fi

if ! command -v docker-compose &>/dev/null; then
    warn "docker-compose não encontrado. Instalando..."
    sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
        -o /usr/local/bin/docker-compose && sudo chmod +x /usr/local/bin/docker-compose
    log "docker-compose instalado."
else
    log "Compose: $(docker-compose --version)"
fi

# ─── 2. Variáveis de ambiente ────────────────────────────────────────────────
step "2/8 — Validando .env"
if [ ! -f ".env" ]; then
    [ -f ".env.example" ] && cp .env.example .env || err ".env e .env.example ausentes."
    echo -e "${RED}Configure o arquivo .env com suas chaves reais e rode novamente!${NC}"
    echo "  nano .env"
    exit 1
fi

REQUIRED_VARS=("POSTGRES_PASSWORD" "REDIS_PASSWORD" "JWT_SECRET_KEY" "BINANCE_API_KEY" "BINANCE_SECRET_KEY" "ANTHROPIC_API_KEY")
MISSING=()
for var in "${REQUIRED_VARS[@]}"; do
    val=$(grep "^${var}=" .env 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    [[ -z "$val" || "$val" == *"CHANGE_ME"* || "$val" == *"SUA_"* || "$val" == *"YOUR_"* ]] && MISSING+=("$var")
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo -e "${RED}Variáveis não configuradas no .env:${NC}"
    for v in "${MISSING[@]}"; do echo "  ❌ $v"; done
    err "Preencha as variáveis acima antes de continuar."
fi
log "Variáveis validadas."

# ─── 3. Diretórios ──────────────────────────────────────────────────────────
step "3/8 — Criando diretórios"
mkdir -p models/weights learning/reports logs
log "Diretórios OK."

# ─── 4. Limpa containers antigos ─────────────────────────────────────────────
step "4/8 — Removendo containers anteriores"
docker-compose down --remove-orphans 2>/dev/null || true
log "Limpo."

# ─── 5. Build ────────────────────────────────────────────────────────────────
step "5/8 — Build Docker (TA-Lib ~3-5min na 1ª vez)"
docker-compose build --no-cache
log "Build concluído."

# ─── 6. Sobe serviços em ordem ───────────────────────────────────────────────
step "6/8 — Iniciando serviços"

docker-compose up -d postgres redis
info "Aguardando PostgreSQL..."
RETRIES=0
until docker-compose exec -T postgres pg_isready -U "${POSTGRES_USER:-robotrader_prod}" &>/dev/null; do
    RETRIES=$((RETRIES+1))
    [ $RETRIES -gt 30 ] && err "PostgreSQL não inicializou. Veja: docker-compose logs postgres"
    sleep 2
done
log "PostgreSQL saudável."

docker-compose up -d zookeeper kafka
sleep 8; log "Kafka iniciado."

docker-compose up -d zia-app
log "ZIA App iniciado."

# ─── 7. Health check ─────────────────────────────────────────────────────────
step "7/8 — Verificando saúde"
info "Aguardando 30s para o app inicializar..."
sleep 30

PORT=$(grep "^API_PORT=" .env 2>/dev/null | cut -d'=' -f2 || echo "8000")
if curl -sf "http://localhost:${PORT}/health" &>/dev/null; then
    log "API respondendo em http://localhost:${PORT}"
else
    warn "API ainda não responde — últimos logs:"
    docker-compose logs --tail=40 zia-app
fi

# ─── 8. Resumo ───────────────────────────────────────────────────────────────
step "8/8 — Pronto!"
echo ""
docker-compose ps
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗"
echo    "║      ZIA TRADER v17 está no ar! 🚀             ║"
echo    "╠══════════════════════════════════════════════════╣"
echo    "║  API:      http://localhost:${PORT}                ║"
echo    "║  Docs:     http://localhost:${PORT}/docs            ║"
echo    "║  Chat:     http://localhost:${PORT}/agent/chat      ║"
echo    "║  WS:       ws://localhost:${PORT}/agent/ws/user1    ║"
echo    "╠══════════════════════════════════════════════════╣"
echo    "║  Logs:   docker-compose logs -f zia-app         ║"
echo    "║  Parar:  ./deploy.sh --stop                      ║"
echo -e "╚══════════════════════════════════════════════════╝${NC}"

#!/bin/bash

# Script de Deploy Automatizado - RoboTrader 2.0
# Uso: ./deploy.sh [environment] [version]
# Exemplo: ./deploy.sh production v1.0.0

set -e

# Configurações
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="robotrader"
REGISTRY="ghcr.io"
REPO_NAME="robotrader"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Funções de log
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Função para mostrar ajuda
show_help() {
    cat << EOF
RoboTrader 2.0 - Script de Deploy Automatizado

Uso: $0 [ENVIRONMENT] [VERSION]

ENVIRONMENT:
    development     Deploy para ambiente de desenvolvimento
    staging         Deploy para ambiente de staging
    production      Deploy para ambiente de produção

VERSION:
    Versão da aplicação (ex: v1.0.0, latest)

Exemplos:
    $0 development latest
    $0 staging v1.0.0
    $0 production v1.2.3

Opções:
    -h, --help      Mostrar esta ajuda
    --dry-run       Simular deploy sem executar
    --force         Forçar deploy mesmo com warnings
    --backup        Criar backup antes do deploy

EOF
}

# Validar argumentos
validate_args() {
    if [[ $# -lt 2 ]]; then
        log_error "Argumentos insuficientes"
        show_help
        exit 1
    fi

    ENVIRONMENT=$1
    VERSION=$2

    case $ENVIRONMENT in
        development|staging|production)
            log_info "Ambiente: $ENVIRONMENT"
            ;;
        *)
            log_error "Ambiente inválido: $ENVIRONMENT"
            show_help
            exit 1
            ;;
    esac

    log_info "Versão: $VERSION"
}

# Verificar dependências
check_dependencies() {
    log_info "Verificando dependências..."
    
    local deps=("docker" "docker-compose" "curl" "jq")
    local missing_deps=()

    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            missing_deps+=("$dep")
        fi
    done

    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "Dependências não encontradas: ${missing_deps[*]}"
        log_error "Instale as dependências e tente novamente"
        exit 1
    fi

    log_success "Todas as dependências estão instaladas"
}

# Verificar se Docker está rodando
check_docker() {
    log_info "Verificando Docker..."
    
    if ! docker info &> /dev/null; then
        log_error "Docker não está rodando"
        exit 1
    fi

    log_success "Docker está rodando"
}

# Carregar variáveis de ambiente
load_env() {
    local env_file=".env.${ENVIRONMENT}"
    
    if [[ -f "$env_file" ]]; then
        log_info "Carregando variáveis de ambiente de $env_file"
        set -a
        source "$env_file"
        set +a
    else
        log_warning "Arquivo de ambiente $env_file não encontrado"
        log_warning "Usando variáveis de ambiente do sistema"
    fi
}

# Fazer backup do banco de dados
backup_database() {
    if [[ "$ENVIRONMENT" == "production" ]]; then
        log_info "Criando backup do banco de dados..."
        
        local backup_dir="backups/$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$backup_dir"
        
        # Backup PostgreSQL
        docker-compose -f docker-compose.prod.yml exec -T postgres pg_dump -U "${POSTGRES_USER:-robotrader}" "${POSTGRES_DB:-robotrader}" > "$backup_dir/postgres_backup.sql"
        
        # Backup InfluxDB
        docker-compose -f docker-compose.prod.yml exec -T influxdb influx backup --bucket "${INFLUXDB_BUCKET:-market_data}" "$backup_dir/influxdb_backup"
        
        log_success "Backup criado em $backup_dir"
    fi
}

# Fazer pull das imagens
pull_images() {
    log_info "Fazendo pull das imagens Docker..."
    
    local api_image="${REGISTRY}/${REPO_NAME}/robotrader-api:${VERSION}"
    local frontend_image="${REGISTRY}/${REPO_NAME}/robotrader-frontend:${VERSION}"
    
    docker pull "$api_image" || {
        log_error "Falha ao fazer pull da imagem da API: $api_image"
        exit 1
    }
    
    docker pull "$frontend_image" || {
        log_error "Falha ao fazer pull da imagem do frontend: $frontend_image"
        exit 1
    }
    
    log_success "Pull das imagens concluído"
}

# Executar testes de saúde
health_check() {
    log_info "Executando testes de saúde..."
    
    local max_attempts=30
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        log_info "Tentativa $attempt/$max_attempts..."
        
        # Verificar API
        if curl -f -s "http://localhost:5000/health" > /dev/null; then
            log_success "API está saudável"
            break
        fi
        
        if [[ $attempt -eq $max_attempts ]]; then
            log_error "API não respondeu após $max_attempts tentativas"
            return 1
        fi
        
        sleep 10
        ((attempt++))
    done
    
    # Verificar Frontend
    if curl -f -s "http://localhost:80/health" > /dev/null; then
        log_success "Frontend está saudável"
    else
        log_error "Frontend não está respondendo"
        return 1
    fi
    
    log_success "Todos os serviços estão saudáveis"
}

# Deploy principal
deploy() {
    log_info "Iniciando deploy para $ENVIRONMENT..."
    
    # Selecionar arquivo docker-compose
    local compose_file
    case $ENVIRONMENT in
        development)
            compose_file="docker-compose.yml"
            ;;
        staging|production)
            compose_file="docker-compose.prod.yml"
            ;;
    esac
    
    # Parar serviços existentes
    log_info "Parando serviços existentes..."
    docker-compose -f "$compose_file" down --remove-orphans
    
    # Fazer backup se necessário
    if [[ "$BACKUP" == "true" ]]; then
        backup_database
    fi
    
    # Fazer pull das imagens
    if [[ "$VERSION" != "latest" ]]; then
        pull_images
    fi
    
    # Iniciar serviços
    log_info "Iniciando serviços..."
    docker-compose -f "$compose_file" up -d
    
    # Aguardar serviços ficarem prontos
    log_info "Aguardando serviços ficarem prontos..."
    sleep 30
    
    # Executar testes de saúde
    if ! health_check; then
        log_error "Deploy falhou nos testes de saúde"
        log_info "Fazendo rollback..."
        docker-compose -f "$compose_file" down
        exit 1
    fi
    
    log_success "Deploy concluído com sucesso!"
}

# Mostrar status dos serviços
show_status() {
    log_info "Status dos serviços:"
    docker-compose -f "docker-compose.prod.yml" ps
    
    log_info "Uso de recursos:"
    docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"
}

# Função principal
main() {
    # Processar argumentos
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --force)
                FORCE=true
                shift
                ;;
            --backup)
                BACKUP=true
                shift
                ;;
            *)
                break
                ;;
        esac
    done
    
    # Validar argumentos
    validate_args "$@"
    
    # Verificar dependências
    check_dependencies
    check_docker
    
    # Carregar variáveis de ambiente
    load_env
    
    # Executar deploy
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "Modo dry-run ativado - simulando deploy"
        log_info "Ambiente: $ENVIRONMENT"
        log_info "Versão: $VERSION"
        log_info "Deploy seria executado agora"
    else
        deploy
        show_status
    fi
}

# Executar função principal
main "$@"


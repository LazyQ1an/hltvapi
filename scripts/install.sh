#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# HLTV Pro Scraper v3.0 — One-Click Install Script
# Target: 30-60 RMB/month servers (Debian/Ubuntu)
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

REPO_URL="https://github.com/LazyQ1an/hltvapi.git"
INSTALL_DIR="${HOME}/hltv-scraper"
CONFIG_PROFILE="low-resource"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "==============================================================="
echo "  HLTV API v3.0 — One-Click Install"
echo "==============================================================="
echo ""

# ── System Requirements ───────────────────────────────────────────

MIN_RAM_MB=800
MIN_DISK_GB=5

check_requirements() {
    log "Checking system requirements..."

    local total_ram=$(free -m | awk '/^Mem:/{print $2}')
    if [ "$total_ram" -lt "$MIN_RAM_MB" ]; then
        err "Insufficient RAM: ${total_ram}MB (minimum ${MIN_RAM_MB}MB)"
        err "This script requires at least 800MB RAM"
        exit 1
    fi
    log "RAM: ${total_ram}MB ${GREEN}✓${NC}"

    local disk_free=$(df -m . | awk 'NR==2{print $4}')
    if [ "$disk_free" -lt "$((MIN_DISK_GB * 1024))" ]; then
        err "Insufficient disk space: ${disk_free}MB (minimum ${MIN_DISK_GB}GB)"
        exit 1
    fi
    log "Disk: ${disk_free}MB free ${GREEN}✓${NC}"
}

# ── Install Dependencies ──────────────────────────────────────────

install_deps() {
    log "Installing system dependencies..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
        curl docker.io docker-compose git python3 python3-pip \
        2>/dev/null || warn "Some packages failed to install"
}

# ── Deploy Application ───────────────────────────────────────────

deploy_app() {
    log "Cloning repository..."
    if [ -d "$INSTALL_DIR" ]; then
        warn "Directory $INSTALL_DIR exists, pulling updates..."
        cd "$INSTALL_DIR"
        git pull
    else
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi

    log "Configuring low-resource profile..."
    cp config/low-resource.yaml config.yaml

    log "Building Docker image..."
    sudo docker compose build --no-cache 2>&1 | tail -1
}

# ── Start Service ─────────────────────────────────────────────────

start_service() {
    log "Starting service..."
    sudo docker compose up -d
    log "Waiting for service to be healthy..."
    sleep 5
    sudo docker compose ps
    log "Service started! Checking health..."
    sudo docker compose exec scraper python main.py info || true
}

# ── Main ─────────────────────────────────────────────────────────

main() {
    check_requirements
    install_deps
    deploy_app
    start_service

    echo ""
    log "==============================================================="
    log "  HLTV API v3.0 安装完成!"
    log "==============================================================="
    echo ""
    log "  API:          http://$(curl -s ifconfig.me):8000"
    log "  Docs:         http://$(curl -s ifconfig.me):8000/docs"
    log "  Dashboard:    streamlit run dashboard.py"
    echo ""
    log "  常用命令:"
    log "    hltv status             查看状态和成功率"
    log "    hltv cleanup            清理过期数据"
    log "    hltv backup             备份数据"
    log "    docker logs -f hltv-pro-scraper  查看实时日志"
    echo ""
}

main "$@"

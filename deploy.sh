#!/bin/bash
# =====================================================================
# HLTV Scraper NG1.0 — CentOS 9 一键部署脚本
# 在服务器上运行: bash deploy.sh
# =====================================================================

set -e

echo "=== HLTV Scraper NG1.0 部署 ==="

# 1. 基础依赖
echo "[1/6] 安装基础工具..."
dnf install -y git wget curl python3 python3-pip 2>&1 | tail -3

# 2. Chrome 浏览器 (Nodriver 必需)
echo "[2/6] 安装 Google Chrome..."
if ! which google-chrome-stable &>/dev/null; then
    curl -sL https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm -o /tmp/chrome.rpm
    dnf install -y /tmp/chrome.rpm 2>&1 | tail -3
    rm -f /tmp/chrome.rpm
fi
google-chrome-stable --version

# 3. Python 虚拟环境
echo "[3/6] 创建 Python 虚拟环境..."
python3 -m venv /opt/hltvapi/venv
source /opt/hltvapi/venv/bin/activate
pip install --upgrade pip

# 4. 克隆项目
echo "[4/6] 克隆 NextGen 分支..."
cd /opt
if [ -d hltvapi ]; then rm -rf hltvapi.bak; mv hltvapi hltvapi.bak; fi
git clone https://github.com/LazyQ1an/hltvapi.git -b NextGen
cd hltvapi
pip install -r requirements.txt

# 5. 快速检查
echo "[5/6] 验证导入..."
python3 -c "
from src.client import HLTVClient
from src.settings import load_settings
from src.stealth import ContentDrivenDelay, PurposelessBrowsingEngine
from src.antibot import FontIsolationManager, CrossModeSessionBridge
from src.core import CrossCoverStrategy, ChallengeResponseBrain, ProcessSandbox
print('NG1.0 所有模块导入成功')
"

# 6. 运行 pytest
echo "[6/6] 运行测试..."
pip install pytest pytest-asyncio
pytest tests/ -q --ignore=tests/capture_fixtures.py --tb=short 2>&1 | tail -8

echo "=== 部署完成 ==="
echo ""
echo "使用方式:"
echo "  source /opt/hltvapi/venv/bin/activate"
echo "  cd /opt/hltvapi"
echo "  python main.py upcoming     # 获取即将进行的比赛"
echo "  python main.py results      # 获取比赛结果"
echo "  python main.py serve        # 启动 API 服务"

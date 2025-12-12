#!/bin/bash
# 智能试卷处理系统 Web 服务启动脚本 (Linux/Mac)

echo "================================================"
echo "   智能试卷处理系统 Web 界面"
echo "================================================"
echo ""

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请先安装 Python"
    exit 1
fi

# 检查是否安装了Web依赖
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "[提示] 首次运行需要安装Web界面依赖..."
    echo ""
    pip3 install -r web_requirements.txt
    echo ""
fi

echo "[启动] 正在启动Web服务器..."
echo ""
echo "访问地址: http://localhost:8000"
echo ""
echo "按 Ctrl+C 停止服务器"
echo ""
echo "================================================"
echo ""

cd web_interface
python3 app.py

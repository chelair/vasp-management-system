@echo off
chcp 65001 >nul
title VASP 后端服务 (FastAPI :3001)
cd /d %~dp0
echo ============================================
echo   VASP 后端服务  端口 3001
echo   关闭本窗口即停止后端
echo ============================================
python backend/run.py
pause

@echo off
chcp 65001 >nul
title VASP 系统一键启动
cd /d %~dp0
start "VASP 后端" cmd /k "cd /d %~dp0 && python backend/run.py"
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath 'npm.cmd' -ArgumentList 'run dev' -WorkingDirectory '%~dp0' -WindowStyle Hidden"
echo 后端(3001)已在窗口运行，前端(5173)已后台静默启动。
exit

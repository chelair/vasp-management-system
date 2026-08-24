@echo off
chcp 65001 >nul
title VASP 前端服务 (后台静默 :5173)
cd /d %~dp0
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath 'npm.cmd' -ArgumentList 'run dev' -WorkingDirectory '%~dp0' -WindowStyle Hidden"
echo 前端已后台静默启动（端口 5173）。
exit

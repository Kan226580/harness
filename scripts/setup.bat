@echo off
chcp 65001 >nul
cd /d "%~dp0..\backend"

uv run uvicorn app.main:app --reload

pause
@echo off
cd /d "%~dp0..\backend"
uv run uvicorn app.main:app --reload
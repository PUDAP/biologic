@echo off
cd /d "%~dp0"
set "PYTHONUTF8=1"
uv run main.py

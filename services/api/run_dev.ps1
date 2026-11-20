# LexLab API — lokal ishga tushirish (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { python -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements-dev.txt }
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m app.seed --dev-users
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

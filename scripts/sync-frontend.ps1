# Dizayn papkasidagi oxirgi frontendni apps/web ga ko'chiradi (repo uchun nusxa).
# Ishlatish:  .\scripts\sync-frontend.ps1  [-Source "C:\...\HuquqiyPlatforma"]
param(
    [string]$Source = "$env:USERPROFILE\Desktop\Lexhakaton\HuquqiyPlatforma"
)
$ErrorActionPreference = "Stop"
$Target = Join-Path $PSScriptRoot "..\apps\web"
if (-not (Test-Path (Join-Path $Source "index.html"))) { throw "index.html topilmadi: $Source" }
New-Item -ItemType Directory -Force $Target | Out-Null
# Ma'lumotlar bazasi, kesh va boshqa vaqtinchalik fayllar repoga kirmaydi
robocopy $Source $Target /MIR /XD __pycache__ .git node_modules /XF *.db *.sqlite *.pyc .env | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy xatosi: $LASTEXITCODE" }
Write-Host "apps/web yangilandi <- $Source"
exit 0

# Builds FocusOs\pgsql\: a portable, minimal copy of PostgreSQL's server
# programs, so FocusOs can run its own database without anyone installing
# PostgreSQL. Copies from an installed PostgreSQL (default: the newest under
# C:\Program Files\PostgreSQL), or from an extracted "Windows x86-64 binaries"
# zip downloaded from https://www.enterprisedb.com/download-postgresql-binaries
#
#   powershell -ExecutionPolicy Bypass -File scripts\get_portable_postgres.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\get_portable_postgres.ps1 -Source D:\pgsql
#
# Only the files the server needs are copied (about 85 MB): no pgAdmin,
# no documentation, no translations.

param([string]$Source = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dest = Join-Path $root "pgsql"

if (-not $Source) {
    $Source = Get-ChildItem "C:\Program Files\PostgreSQL" -Directory -ErrorAction SilentlyContinue |
        Sort-Object { [int]($_.Name -replace '\D', '') } -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Source -or -not (Test-Path (Join-Path $Source "bin\postgres.exe"))) {
    throw "No PostgreSQL found. Install PostgreSQL, or download the Windows binaries zip, extract it and pass -Source <folder that contains bin\postgres.exe>."
}
Write-Host "Copying PostgreSQL from $Source"

if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Force (Join-Path $dest "bin"), (Join-Path $dest "lib"), (Join-Path $dest "share") | Out-Null

# bin: the server programs plus every DLL next to them, except pgAdmin's GUI (wx*)
foreach ($exe in "postgres.exe", "pg_ctl.exe", "initdb.exe", "psql.exe", "pg_isready.exe", "pg_dump.exe") {
    Copy-Item (Join-Path $Source "bin\$exe") (Join-Path $dest "bin")
}
Get-ChildItem (Join-Path $Source "bin") -Filter *.dll |
    Where-Object { $_.Name -notlike "wx*" } |
    Copy-Item -Destination (Join-Path $dest "bin")

# lib: server modules (PL/pgSQL, text search dictionaries, encoding conversions, ...)
Get-ChildItem (Join-Path $Source "lib") -Filter *.dll | Copy-Item -Destination (Join-Path $dest "lib")

# share: catalog templates, time zones, extensions; translations are not needed
Get-ChildItem (Join-Path $Source "share") | Where-Object { $_.Name -notin @("locale", "doc", "man") } |
    Copy-Item -Destination (Join-Path $dest "share") -Recurse

$sizeMb = [math]::Round(((Get-ChildItem $dest -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
$version = & (Join-Path $dest "bin\postgres.exe") --version
Write-Host "Portable PostgreSQL ready in $dest ($sizeMb MB): $version"

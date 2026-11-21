# One-time PostgreSQL setup for FocusOs (Windows).
#
#   powershell -ExecutionPolicy Bypass -File db\setup.ps1
#
# Creates the login role `focus_user` and the database `study_tracker`, then
# loads schema.sql and logic.sql. Safe to run again: existing objects are kept.
#
# Passwords never go into the project. The focus_user password is generated
# here and saved in %APPDATA%\postgresql\pgpass.conf, PostgreSQL's standard
# password file, which psql, libpq (the C++ tracker) and psycopg read
# automatically. The postgres superuser password must already be in that file
# or be typed when psql asks for it.

param(
    [string]$PgBin = "",
    [string]$Role = "focus_user",
    [string]$Database = "study_tracker"
)

$ErrorActionPreference = "Stop"

if (-not $PgBin) {
    $PgBin = Get-ChildItem "C:\Program Files\PostgreSQL" -Directory |
        Sort-Object { [int]($_.Name -replace '\D', '') } -Descending |
        Select-Object -First 1 | ForEach-Object { Join-Path $_.FullName "bin" }
}
$psql = Join-Path $PgBin "psql.exe"
if (-not (Test-Path $psql)) { throw "psql.exe not found in $PgBin" }

$pgpassDir = Join-Path $env:APPDATA "postgresql"
$pgpass = Join-Path $pgpassDir "pgpass.conf"
New-Item -ItemType Directory -Force $pgpassDir | Out-Null

function Invoke-Psql([string[]]$PsqlArgs, [string]$Stdin = $null) {
    if ($null -ne $Stdin) { $out = $Stdin | & $psql -X -v ON_ERROR_STOP=1 @PsqlArgs }
    else { $out = & $psql -X -v ON_ERROR_STOP=1 @PsqlArgs }
    if ($LASTEXITCODE -ne 0) { throw "psql failed: $($PsqlArgs -join ' ')" }
    return $out
}

$asPostgres = @("-h", "localhost", "-U", "postgres", "-d", "postgres")

# 1. Login role
$roleExists = Invoke-Psql ($asPostgres + @("-tAc", "SELECT 1 FROM pg_roles WHERE rolname = '$Role'"))
if ($roleExists -ne "1") {
    $chars = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $pw = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })

    # psql interpolates :'pw' as a safely quoted literal (stdin, not -c).
    Invoke-Psql ($asPostgres + @("-v", "pw=$pw")) "CREATE ROLE $Role LOGIN PASSWORD :'pw';" | Out-Null

    Add-Content -Path $pgpass -Encoding ascii -Value "`nlocalhost:5432:*:${Role}:$pw`n127.0.0.1:5432:*:${Role}:$pw"
    icacls $pgpass /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
    Remove-Variable pw
    Write-Host "Created role $Role (password saved to $pgpass)"
} else {
    Write-Host "Role $Role already exists"
}

# 2. Database
$dbExists = Invoke-Psql ($asPostgres + @("-tAc", "SELECT 1 FROM pg_database WHERE datname = '$Database'"))
if ($dbExists -ne "1") {
    Invoke-Psql ($asPostgres + @("-c", "CREATE DATABASE $Database OWNER $Role ENCODING 'UTF8' TEMPLATE template0")) | Out-Null
    Write-Host "Created database $Database"
} else {
    Write-Host "Database $Database already exists"
}

# 3. Tables and views, as the application role
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$asApp = @("-h", "localhost", "-U", $Role, "-d", $Database, "-q")
Invoke-Psql ($asApp + @("-f", (Join-Path $here "schema.sql"))) | Out-Null
Invoke-Psql ($asApp + @("-f", (Join-Path $here "logic.sql"))) | Out-Null
Write-Host "Loaded schema.sql and logic.sql into $Database"

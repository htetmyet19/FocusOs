# Packages FocusOs into dist\FocusOs-<date>.zip for people who should not have
# to install PostgreSQL or a compiler. The zip contains:
#   - every file tracked by git (no config.ini, no secrets, no caches)
#   - pgsql\                     portable PostgreSQL (scripts\get_portable_postgres.ps1)
#   - tracker\build\focus_tracker.exe + the DLLs next to it
#   - FocusOs.exe + _internal\    the desktop app (PyInstaller), so users need no Python
# They unzip it and double-click FocusOs.exe (or start.bat, which opens it).
#
#   powershell -ExecutionPolicy Bypass -File scripts\make_release.ps1
#   ... -NoExe            skip the desktop .exe (users then need Python 3.10+)
#   ... -Python <path>    Python with the dashboard packages + pyinstaller (default .venv)

param(
    [string]$Python = ".venv\Scripts\python.exe",
    [switch]$NoExe
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

if (-not (Test-Path "pgsql\bin\postgres.exe")) { throw "pgsql\ is missing. Run scripts\get_portable_postgres.ps1 first." }
if (-not (Test-Path "tracker\build\focus_tracker.exe")) { throw "Build the tracker first (see README)." }
if (-not $NoExe) {
    & $Python -m PyInstaller --version *> $null
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller not found for $Python. Run: $Python -m pip install pyinstaller  (or use -NoExe)" }
}

$stamp = Get-Date -Format "yyyy-MM-dd"
$stage = Join-Path $root "dist\FocusOs"
$zip = Join-Path $root "dist\FocusOs-$stamp.zip"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null

# 1. Project files: tracked + new files, minus everything .gitignore excludes
#    (config.ini, pgsql\, build output, caches), so nothing private gets in.
git ls-files --cached --others --exclude-standard | Where-Object { Test-Path $_ -PathType Leaf } | ForEach-Object {
    $target = Join-Path $stage $_
    New-Item -ItemType Directory -Force (Split-Path -Parent $target) | Out-Null
    Copy-Item $_ $target
}
# 2. Portable PostgreSQL
Copy-Item "pgsql" (Join-Path $stage "pgsql") -Recurse
# 3. The built tracker and its DLLs (no CMake cache or object files)
$buildOut = Join-Path $stage "tracker\build"
New-Item -ItemType Directory -Force $buildOut | Out-Null
Copy-Item "tracker\build\focus_tracker.exe", "tracker\build\*.dll" $buildOut

# 4. The desktop app: FocusOs.exe + _internal\ at the top of the folder
if (-not $NoExe) {
    & $Python -m PyInstaller "tracker\dashboard\FocusOs.spec" --noconfirm --log-level WARN `
        --distpath "dist\pyi" --workpath "dist\pyi-build"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
    Copy-Item "dist\pyi\FocusOs\*" $stage -Recurse -Force
}

# Never ship local settings or data, even if they somehow got staged.
Get-ChildItem $stage -Recurse -Include "config.ini", "*.joblib", "focus_session.log", "pgpass.conf" -File |
    Remove-Item -Force

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Release ready: $zip ($mb MB)"
Write-Host $(if ($NoExe) { "Users unzip it and double-click start.bat." } else { "Users unzip it and double-click FocusOs.exe." })

# Lists apps installed for the current user as JSON: [{ name, exe, source }]
#   desktop: Start menu shortcuts (.lnk) resolved to their .exe target
#   store:   Microsoft Store (MSIX/AppX) packages, executable from AppxManifest.xml
# Used by the dashboard's "Add apps" picker. Read-only: changes nothing.

$ErrorActionPreference = 'SilentlyContinue'
$apps = New-Object System.Collections.Generic.List[object]

# Desktop apps from the Start menu (all users + current user)
$shell = New-Object -ComObject WScript.Shell
$startMenus = @(
    (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs'),
    (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs')
)
foreach ($dir in $startMenus) {
    Get-ChildItem -Path $dir -Recurse -Filter *.lnk | ForEach-Object {
        $target = $shell.CreateShortcut($_.FullName).TargetPath
        # Skip Windows' own tools (regedit, charmap, ...): they live under C:\Windows.
        if ($target -and $target.ToLower().EndsWith('.exe') -and -not $target.StartsWith($env:WINDIR, [StringComparison]::OrdinalIgnoreCase)) {
            $apps.Add([pscustomobject]@{ name = $_.BaseName; exe = [IO.Path]::GetFileName($target); source = 'desktop' })
        }
    }
}

# Store apps. Only those that appear in the Start menu: Get-StartApps lists
# them as "<PackageFamilyName>!<AppId>" with the friendly, localised name.
# Hidden helpers (proxies, background tasks, runtimes) are not in that list.
$startNames = @{}
Get-StartApps | ForEach-Object { $startNames[$_.AppID] = $_.Name }

Get-AppxPackage | Where-Object { -not $_.IsFramework -and -not $_.IsResourcePackage } | ForEach-Object {
    $pkg = $_
    $manifestPath = Join-Path $pkg.InstallLocation 'AppxManifest.xml'
    if (-not (Test-Path $manifestPath)) { return }
    $manifest = [xml](Get-Content $manifestPath -Raw)
    foreach ($app in @($manifest.Package.Applications.Application)) {
        if (-not $app.Executable -or -not $app.Executable.ToLower().EndsWith('.exe')) { continue }
        $aumid = "$($pkg.PackageFamilyName)!$($app.Id)"
        if (-not $startNames.ContainsKey($aumid)) { continue }
        $apps.Add([pscustomobject]@{ name = $startNames[$aumid]; exe = [IO.Path]::GetFileName($app.Executable); source = 'store' })
    }
}

$apps | ConvertTo-Json -Compress

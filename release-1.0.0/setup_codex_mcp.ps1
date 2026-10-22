$ErrorActionPreference = 'Stop'
$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallRoot = Join-Path $HOME 'Documents\ChatGPT_Blender_Bridge'
$BlenderRoot = Join-Path $env:APPDATA 'Blender Foundation\Blender'
$AddonSource = Join-Path $SourceRoot 'blender_addon\chatgpt_blender_bridge'
$ServerSource = Join-Path $SourceRoot 'mcp_server'

if (!(Test-Path (Join-Path $AddonSource '__init__.py'))) {
    throw "Add-on-Quelldatei nicht gefunden: $AddonSource"
}
if (!(Test-Path (Join-Path $ServerSource 'mcp_bridge_server.py'))) {
    throw "MCP-Server nicht gefunden: $ServerSource"
}

# Install the server files in Documents without touching Blender projects.
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$ServerInstall = Join-Path $InstallRoot 'mcp_server'
New-Item -ItemType Directory -Force -Path $ServerInstall | Out-Null
Copy-Item -Path (Join-Path $ServerSource '*') -Destination $ServerInstall -Recurse -Force
Copy-Item -Path (Join-Path $SourceRoot 'README_DE.md') -Destination $InstallRoot -Force
Copy-Item -Path (Join-Path $SourceRoot 'CHANGELOG.md') -Destination $InstallRoot -Force

# Detect the highest installed Blender profile folder (e.g. 5.2).
$VersionDirs = @()
if (Test-Path $BlenderRoot) {
    $VersionDirs = Get-ChildItem $BlenderRoot -Directory | Where-Object {
        try { ([version]$_.Name) -ge ([version]'4.2') } catch { $false }
    } | Sort-Object { [version]$_.Name } -Descending
}
if (!$VersionDirs -or $VersionDirs.Count -eq 0) {
    throw "Kein Blender-Benutzerprofil ab 4.2 unter '$BlenderRoot' gefunden. Installiere das Add-on manuell; siehe README_DE.md."
}
$BlenderVersion = $VersionDirs[0].Name
$AddonInstallRoot = Join-Path $BlenderRoot "$BlenderVersion\scripts\addons"
$AddonInstall = Join-Path $AddonInstallRoot 'chatgpt_blender_bridge'
New-Item -ItemType Directory -Force -Path $AddonInstallRoot | Out-Null
if (Test-Path $AddonInstall) {
    $backup = "$AddonInstall.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Copy-Item $AddonInstall $backup -Recurse -Force
    Write-Host "Vorheriges Add-on gesichert: $backup" -ForegroundColor Yellow
}
Copy-Item -Path (Join-Path $AddonSource '*') -Destination $AddonInstall -Recurse -Force
Write-Host "Add-on kopiert nach: $AddonInstall" -ForegroundColor Green

# Append the Codex MCP entry only if it is not already present. Existing config is backed up.
$CodexDir = Join-Path $HOME '.codex'
$ConfigPath = Join-Path $CodexDir 'config.toml'
New-Item -ItemType Directory -Force -Path $CodexDir | Out-Null
if (!(Test-Path $ConfigPath)) { New-Item -ItemType File -Path $ConfigPath | Out-Null }
$ConfigText = Get-Content $ConfigPath -Raw
if ($ConfigText -match '(?m)^\[mcp_servers\.chatgpt_blender_bridge\]\s*$') {
    Write-Host 'Codex-MCP-Abschnitt existiert bereits; config.toml wurde nicht verändert.' -ForegroundColor Yellow
} else {
    $PythonCommand = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (!$PythonCommand) { $PythonCommand = 'python' }
    $ServerPath = Join-Path $ServerInstall 'mcp_bridge_server.py'
    $EscapedPython = $PythonCommand.Replace('\', '\\').Replace('"', '\"')
    $EscapedServer = $ServerPath.Replace('\', '\\').Replace('"', '\"')
    $BackupPath = "$ConfigPath.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Copy-Item $ConfigPath $BackupPath -Force
    $Block = "`r`n[mcp_servers.chatgpt_blender_bridge]`r`ncommand = `"$EscapedPython`"`r`nargs = [`"$EscapedServer`"]`r`n"
    Add-Content -Path $ConfigPath -Value $Block -Encoding UTF8
    Write-Host "Codex-Konfiguration erweitert. Backup: $BackupPath" -ForegroundColor Green
}

Write-Host ''
Write-Host 'Nächste Schritte:' -ForegroundColor Cyan
Write-Host '1. Blender neu starten, ChatGPT Blender Bridge in Add-ons aktivieren.'
Write-Host '2. In der 3D-Ansicht N drücken und den Tab ChatGPT prüfen.'
Write-Host '3. Codex vollständig neu starten, damit der MCP-Eintrag geladen wird.'
Write-Host "Blender-Profil erkannt: $BlenderVersion"
Write-Host "Lokaler MCP-Server: $ServerInstall"

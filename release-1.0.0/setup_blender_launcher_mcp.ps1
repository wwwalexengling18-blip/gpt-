$ErrorActionPreference = 'Stop'

$SourceScript = Join-Path $PSScriptRoot 'mcp_server\blender_launcher_mcp.py'
if (!(Test-Path -LiteralPath $SourceScript -PathType Leaf)) {
    throw "Launcher-Server nicht gefunden: $SourceScript. Führe das Skript aus release-1.0.0 aus."
}
$InstallRoot = Join-Path $HOME 'Documents\ChatGPT_Blender_Bridge\mcp_server'
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$TargetScript = Join-Path $InstallRoot 'blender_launcher_mcp.py'
Copy-Item -LiteralPath $SourceScript -Destination $TargetScript -Force
Write-Host "Launcher kopiert nach: $TargetScript" -ForegroundColor Green

$PythonCommand = (Get-Command python -ErrorAction SilentlyContinue).Source
if (!$PythonCommand) { $PythonCommand = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (!$PythonCommand) {
    throw "Python wurde nicht gefunden. Installiere Python 3.11+ oder trage einen gültigen Pfad manuell in die MCP-Konfiguration ein."
}
$CodexDir = Join-Path $HOME '.codex'
New-Item -ItemType Directory -Force -Path $CodexDir | Out-Null
$ConfigPath = Join-Path $CodexDir 'config.toml'
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    $ConfigText = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
} else {
    $ConfigText = ''
}

if ($ConfigText -match '(?m)^\[mcp_servers\.blender_launcher\]\s*$') {
    Write-Host "Der MCP-Abschnitt [mcp_servers.blender_launcher] existiert bereits." -ForegroundColor Yellow
    Write-Host 'Die vorhandene Konfiguration wurde nicht verändert. Prüfe den command/args-Pfad:'
    Write-Host "  $TargetScript"
    exit 0
}
if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
    $Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $BackupPath = "$ConfigPath.backup-$Stamp"
    Copy-Item -LiteralPath $ConfigPath -Destination $BackupPath
    Write-Host "Konfigurations-Backup: $BackupPath" -ForegroundColor Cyan
}
$EscapedPython = $PythonCommand.Replace('\', '\\').Replace('"', '\"')
$EscapedServer = $TargetScript.Replace('\', '\\').Replace('"', '\"')
$Block = @"

# Added by ChatGPT Blender Bridge launcher setup.
[mcp_servers.blender_launcher]
command = "$EscapedPython"
args = ["$EscapedServer"]
"@
[System.IO.File]::WriteAllText($ConfigPath, $ConfigText + $Block + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

Write-Host "MCP-Konfiguration ergänzt: $ConfigPath" -ForegroundColor Green
Write-Host ''
Write-Host 'Nächste Schritte:' -ForegroundColor Cyan
Write-Host '1. ChatGPT Desktop vollständig beenden und neu starten.'
Write-Host '2. Einstellungen > MCP-Server öffnen und blender_launcher auf aktiviert prüfen.'
Write-Host '3. Im Chat /mcp eingeben, um verbundene MCP-Server anzuzeigen.'
Write-Host '4. Zuerst get_launcher_status oder find_blender_installations aufrufen.'
Write-Host '5. start_blender nur nach ausdrücklicher eigener Anfrage verwenden.'
Write-Host 'Für Szenensteuerung muss das Blender-Add-on zusätzlich aktiv sein.'

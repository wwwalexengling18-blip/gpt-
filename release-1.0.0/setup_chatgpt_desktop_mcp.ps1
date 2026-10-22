$ErrorActionPreference = 'Stop'

# ChatGPT Desktop (standard app) setup.
# Intentionally does NOT read or modify %USERPROFILE%\.codex\config.toml.

$SourceScript = Join-Path $PSScriptRoot 'mcp_server\blender_launcher_mcp.py'
if (!(Test-Path -LiteralPath $SourceScript -PathType Leaf)) {
    throw "Launcher-Server nicht gefunden: $SourceScript. Führe das Skript aus dem release-1.0.0-Verzeichnis aus."
}

$PythonCommand = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (!$PythonCommand) { $PythonCommand = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (!$PythonCommand) { $PythonCommand = (Get-Command py.exe -ErrorAction SilentlyContinue).Source }
if (!$PythonCommand) {
    throw "Python wurde nicht gefunden. Installiere Python 3.11 oder neuer und führe dieses Skript erneut aus."
}

$InstallRoot = Join-Path $HOME 'Documents\ChatGPT_Blender_Bridge\mcp_server'
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$TargetScript = Join-Path $InstallRoot 'blender_launcher_mcp.py'

if (Test-Path -LiteralPath $TargetScript -PathType Leaf) {
    $Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $BackupPath = "$TargetScript.backup-$Stamp"
    Copy-Item -LiteralPath $TargetScript -Destination $BackupPath
    Write-Host "Vorhandener Launcher gesichert: $BackupPath" -ForegroundColor Cyan
}
Copy-Item -LiteralPath $SourceScript -Destination $TargetScript -Force

Write-Host ''
Write-Host 'Lokaler Launcher für die normale ChatGPT-Desktop-App wurde vorbereitet.' -ForegroundColor Green
Write-Host "Python-Befehl: $PythonCommand"
Write-Host "MCP-Serverdatei: $TargetScript"
Write-Host ''
Write-Host 'Dieses Skript hat KEINE Codex-Konfiguration geändert.' -ForegroundColor Yellow
Write-Host ''
Write-Host 'Jetzt in der ChatGPT-Desktop-App konfigurieren:' -ForegroundColor Cyan
Write-Host '1. ChatGPT Desktop öffnen.'
Write-Host '2. Einstellungen > MCP-Server > Server hinzufügen öffnen.'
Write-Host '3. Transport STDIO auswählen.'
Write-Host '4. Name: blender_launcher'
Write-Host "5. Befehl: $PythonCommand"
Write-Host "6. Argument: $TargetScript"
Write-Host '7. Speichern und den MCP-Server bzw. ChatGPT Desktop neu starten.'
Write-Host '8. Zuerst get_launcher_status oder find_blender_installations testen.'
Write-Host ''
Write-Host 'Falls die Desktop-App auf deinem Konto keinen Menüpunkt MCP-Server bietet, kann dieses Skript ihn nicht freischalten.'
Write-Host 'Für Szenensteuerung muss zusätzlich das Blender-Add-on aktiv sein und 127.0.0.1:9877 anzeigen.'

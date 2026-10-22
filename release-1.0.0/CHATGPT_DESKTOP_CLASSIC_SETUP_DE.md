# Einrichtung für die normale ChatGPT-Desktop-App (nicht Codex)

Dieser Leitfaden ist für die normale ChatGPT-Desktop-App unter Windows gedacht. Er führt nicht durch Codex und verändert keine Codex-Konfigurationsdatei.

## Was diese Erweiterung macht

Die vorhandene Datei mcp_server/blender_launcher_mcp.py ist ein lokaler MCP-Server. Sie stellt drei Werkzeuge bereit:
- get_launcher_status: liest installierte/aktive Blender-Prozesse und prüft die lokale Bridge.
- find_blender_installations: sucht Blender an üblichen Installationsorten.
- start_blender: startet Blender nur nach expliziter Anfrage mit confirm=true. Freie Shell-Befehle, beliebige Blender-Skripte und das Öffnen von Projektdateien werden nicht unterstützt.

## Installation

1. Entpacke den GitHub-Arbeitszweig.
2. Öffne PowerShell als normaler Benutzer und wechsle in den Ordner release-1.0.0.
3. Führe aus:

   pwsh -ExecutionPolicy Bypass -File .\setup_chatgpt_desktop_mcp.ps1

4. Das Skript kopiert den Launcher nach Documents\ChatGPT_Blender_Bridge\mcp_server\blender_launcher_mcp.py und sucht nach einer Python-Installation. Ein bereits vorhandener Launcher wird vor dem Ersetzen mit Zeitstempel gesichert.
5. Öffne die normale ChatGPT-Desktop-App. Gehe zu Einstellungen > MCP-Server > Server hinzufügen.
6. Wähle STDIO und trage ein:
   - Name: blender_launcher
   - Befehl: der vom Installationsskript ausgegebene Python-Pfad
   - Argument: der vom Installationsskript ausgegebene Pfad zur blender_launcher_mcp.py
7. Speichere den Server und starte ihn bzw. ChatGPT Desktop neu.
8. Prüfe in den MCP-Server-Einstellungen, ob der Server aktiv ist. Im Chat kannst du nach verfügbaren MCP-Servern bzw. den Werkzeugen suchen und zuerst get_launcher_status aufrufen.
9. Erst nachdem die Statusabfrage funktioniert, bitte die App ausdrücklich, Blender zu starten.

## Keine Codex-Konfiguration

Dieses Setup-Skript liest, erstellt oder bearbeitet nicht die Datei %USERPROFILE%\.codex\config.toml. Die Registrierung erfolgt über die MCP-Server-Einstellungen der normalen ChatGPT-Desktop-App.

## Grenzen und Sicherheit

- Ob die MCP-Server-Einstellungen in deiner installierten ChatGPT-Desktop-Version und deinem Konto verfügbar sind, muss direkt in der App geprüft werden. Ein Installationsskript kann eine fehlende Produktfunktion oder Kontoberechtigung nicht freischalten.
- ChatGPT im Browser kann eine nur lokal gebundene Adresse wie 127.0.0.1 nicht direkt erreichen. Dieser Weg ist für einen Desktop-Host vorgesehen, der lokale STDIO-MCP-Server unterstützt.
- Der Launcher sucht Blender in üblichen Windows-Ordnern. Wird Blender nicht gefunden, muss BLENDER_EXECUTABLE im MCP-Server-Eintrag auf eine vertrauenswürdige blender.exe zeigen, falls die Oberfläche Umgebungsvariablen unterstützt.
- start_blender prüft, ob Blender bereits läuft, und verlangt confirm=true. Es startet keine Blender-Skripte und öffnet keine Datei.
- Ein erfolgreicher Prozessstart bestätigt noch nicht, dass das Blender-Add-on geladen wurde. Prüfe danach erneut den Status und die Anzeige 127.0.0.1:9877 im Blender-Add-on.

## Teststatus

Quellcode und Installationsdatei sind in GitHub hinterlegt und nach dem Commit erneut abgerufen worden. Noch nicht durchgeführt wurden die Installation auf deinem PC, das Hinzufügen über deine ChatGPT-Desktop-Oberfläche und ein echter Blender-Start.

# Blender-Launcher für ChatGPT Desktop – Installationshinweise

Dieser Zusatz ist ein separater lokaler MCP-Server. Er startet Blender nur nach einer ausdrücklichen Nutzeranfrage. Er führt keine Blender-Python-Skripte aus, öffnet keine Projektdateien und akzeptiert keine freien Shell-Befehle.

## Dateien
- mcp_server/blender_launcher_mcp.py: stdio-MCP-Server mit Statusabfrage, Suche nach Blender-Installationen und Startfunktion.
- setup_blender_launcher_mcp.ps1: kopiert den Server nach Documents\ChatGPT_Blender_Bridge\mcp_server und ergänzt die lokale MCP-Konfiguration mit vorheriger Sicherung.
- tests/test_blender_launcher_mcp.py: nicht-destruktive Protokoll- und Bestätigungstests.

## Installation
1. Öffne PowerShell als normaler Benutzer, nicht als Administrator.
2. Wechsle im geklonten Repository in release-1.0.0.
3. Führe aus:
   pwsh -ExecutionPolicy Bypass -File .\setup_blender_launcher_mcp.ps1
4. Beende ChatGPT Desktop vollständig und starte die App neu.
5. Prüfe in Einstellungen > MCP-Server, ob blender_launcher eingetragen und aktiviert ist. In unterstützten Desktop-/Codex-Hosts werden lokale stdio-MCP-Server als lokale Prozesse ausgeführt. Falls die Konfiguration nicht automatisch geladen wird, füge den Server in den MCP-Einstellungen manuell hinzu: Befehl = dein Python-Pfad, Argument = der vollständige Pfad zur installierten blender_launcher_mcp.py.
6. Rufe zuerst get_launcher_status oder find_blender_installations auf. Wenn keine Installation gefunden wird, konfiguriere BLENDER_EXECUTABLE mit dem vollständigen Pfad zu einer vertrauenswürdigen blender.exe, zum Beispiel C:\Program Files\Blender Foundation\Blender 5.2\blender.exe.

## Sicherheitsgrenzen
- start_blender verlangt confirm=true. Der Client soll es nur auf eine explizite Aufforderung des Nutzers aufrufen.
- Der Launcher nutzt feste Prozessargumente, shell=False und die Windows-Prozessliste, damit kein zweiter Blender-Prozess gestartet wird, wenn bereits einer läuft.
- Für den optionalen Bridge-Test sendet er ausschließlich get_status an 127.0.0.1:9877.
- Die Installation ändert config.toml nur nach einem zeitgestempelten Backup. Eine bereits vorhandene Sektion mcp_servers.blender_launcher wird nicht überschrieben.
- Ein gemeldeter Prozessstart beweist noch nicht, dass Blender vollständig geladen oder die Add-on-Bridge aktiv ist. Rufe den Status danach erneut auf.

## Grenzen
Diese GitHub-Änderung installiert den Launcher nicht selbst auf deinem PC und aktiviert keine MCP-Verbindung in dieser Unterhaltung. Der lokale Server muss auf deinem Rechner laufen; die verwendete ChatGPT-Desktop-/Codex-Oberfläche muss lokale MCP-Server unterstützen und den Launcher aktiviert haben. Ein Browser-Chat kann nicht direkt auf 127.0.0.1 deines PCs zugreifen.

Noch nicht verifiziert: Live-Start von Blender auf deinem Rechner und Verbindung zur dort laufenden Add-on-Instanz.

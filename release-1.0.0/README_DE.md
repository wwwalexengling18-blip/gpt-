# ChatGPT Blender Bridge – Local MCP 1.0.0

Kostenloses, quelloffenes Grundpaket zur Steuerung von Blender über MCP. Zielversion ist **Blender 5.2.2 LTS** (aktuelle LTS am 12. Oktober 2026); der Add-on-Code ist auf Blender 4.2+ ausgelegt. Es verwendet nur Blender-Python und die Python-Standardbibliothek – keine kostenpflichtige Bibliothek und kein Plugin-eigenes Nutzungslimit.

## Enthaltene Dateien

- `blender_addon/chatgpt_blender_bridge/__init__.py` – Blender-Add-on mit lokalem Bridge-Server, Freigabe-Panel und Audit-Log.
- `mcp_server/mcp_bridge_server.py` – MCP-Server über `stdio`, etwa für Codex und andere lokale MCP-Clients.
- `mcp_server/mcp_http_server.py` – optionaler, token-geschützter Streamable-HTTP-MCP-Endpunkt für Clients, die einen solchen Server über einen unterstützten sicheren Tunnel erreichen können.
- `mcp_server/tool_schemas.json` – MCP-Werkzeugbeschreibungen.
- `setup_codex_mcp.ps1` – optionale Windows-Installation mit Backup der Codex-Konfiguration.

## Installation unter Windows

1. Lade entweder das separate `ChatGPT_Blender_Bridge_Addon_1.0.0.zip` herunter oder entpacke das Gesamtpaket in einen normalen Ordner, zum Beispiel `Documents\ChatGPT_Blender_Bridge`.
2. In Blender **Edit > Preferences > Extensions** öffnen, im Menü oben rechts **Install from Disk** wählen und `ChatGPT_Blender_Bridge_Addon_1.0.0.zip` auswählen. Das ZIP enthält `blender_manifest.toml` und `__init__.py` im passenden Extension-Format.
3. Nach der Installation **ChatGPT Blender Bridge** aktivieren. In der 3D-Ansicht `N` drücken und den Tab **ChatGPT** öffnen. Der Status sollte `läuft` und `127.0.0.1:9877` anzeigen.
4. Für eine lokale Codex-Verbindung kann `setup_codex_mcp.ps1` aus dem entpackten Gesamtpaket in PowerShell ausgeführt werden. Es sichert eine vorhandene Codex-Konfiguration, bevor es einen neuen Eintrag anhängt. Danach Codex vollständig neu starten. Das Skript kann alternativ das Add-on als Legacy-Add-on in den Benutzerordner kopieren.

Falls du lieber manuell konfigurierst, ergänze am Ende von `%USERPROFILE%\.codex\config.toml` den folgenden Abschnitt. Passe den Pfad bei Bedarf an und überschreibe keine vorhandenen MCP-Einträge:

```toml
[mcp_servers.chatgpt_blender_bridge]
command = "python"
args = ["C:\\Users\\wwwal\\Documents\\ChatGPT_Blender_Bridge\\mcp_server\\mcp_bridge_server.py"]
```

## Verfügbare Werkzeuge

`get_status`, `scene_overview`, `list_objects`, `inspect_object`, `create_primitive`, `create_camera`, `create_light`, `set_transform`, `duplicate_object`, `delete_object`, `create_material`, `assign_material`, `set_frame`, `keyframe_transform`, `validate_scene`, `repair_scene`, `render_preview`, `save_blend_copy`, `execute_python`.

Szenenprüfungen sind nicht-destruktiv. `repair_scene` bietet eine begrenzte Auswahl sicherer Reparaturen (Normalen neu berechnen, Standardmaterial setzen, Materialknoten aktivieren, vorhandene Kamera setzen). Es versucht nicht, automatisch jedes denkbare Modell- oder Szenenproblem zu erraten.

## Freigaben, Dateisicherheit und Protokollierung

- Der Blender-Bridge-Port lauscht ausschließlich auf `127.0.0.1`; er wird nicht im Heimnetz geöffnet.
- Löschvorgänge, Rendern, Projektkopien und Python-Ausführung verlangen standardmäßig eine Freigabe im Blender-Tab **ChatGPT**.
- Gespeicherte `.blend`-Kopien und Render-Vorschauen dürfen nur im konfigurierten Projektordner abgelegt werden. Vorhandene Dateien werden nicht überschrieben.
- Beliebige Python-Ausführung ist zunächst deaktiviert. Wenn sie in den Add-on-Präferenzen eingeschaltet wird, läuft der Code mit den vollständigen Rechten des Blender-Prozesses – **ohne Sandbox**. Nur bei vertrauenswürdigen Clients aktivieren und jede Anfrage prüfen.
- Das vollständige JSONL-Audit-Log liegt im Projektordner als `chatgpt_blender_bridge_audit.jsonl`. Es protokolliert Anfrageparameter, Freigaben, Ergebnisse und Fehler. Dazu kann auch übermittelter Python-Code gehören. Wer dies nicht möchte, kann das Log in den Add-on-Präferenzen abschalten.
- Eine Änderung an Geometrie, Shadern oder Animationen kann fachlich falsch sein. Vor größeren Arbeiten sollte die `.blend`-Datei selbst gesichert werden.

## Optional: HTTP-MCP für unterstützte Remote-Clients

`mcp_http_server.py` bindet ebenfalls nur an `127.0.0.1` und stellt `/mcp` auf Port `8765` bereit. Es benötigt einen Bearer-Token. Für einen festen Token kann in PowerShell vor dem Start gesetzt werden:

```powershell
$env:BLENDER_MCP_HTTP_TOKEN = "HIER_EIN_LANGES_ZUFAELLIGES_GEHEIMNIS_EINTRAGEN"
$env:BLENDER_MCP_ALLOWED_ORIGINS = "https://chatgpt.com,https://chat.openai.com"
python .\mcp_server\mcp_http_server.py
```

Der HTTP-Endpunkt ist **kein öffentlicher Server**. Für einen entfernten Client ist ein vom Anbieter unterstützter sicherer MCP-Tunnel oder eine gleichwertige abgesicherte TLS-Verbindung erforderlich. Nicht per Router-Portweiterleitung öffentlich freigeben. Ein Tunnel muss auf den lokalen Endpunkt `127.0.0.1:8765/mcp` führen und der Client muss den Bearer-Token mitsenden.

## Wichtige Grenze bei ChatGPT

MCP ist modellunabhängig; dieses Paket beansprucht keine besondere interne Verbindung zu einem Modell namens „GPT-6 Astra“. Ob ChatGPT selbst den Endpunkt einbinden und schreibende Aktionen ausführen darf, hängt von der jeweils verfügbaren ChatGPT-App-/MCP-Funktion und dem Konto ab. Das Add-on kann solche Host- oder Tarifgrenzen nicht umgehen. Die lokale `stdio`-Verbindung ist für kompatible lokale MCP-Clients vorgesehen.

## Fehlerbehebung

- **Portfehler:** Prüfe, ob ein anderes Add-on bereits Port `9877` verwendet. Ändere den Port in den Add-on-Präferenzen und im MCP-Server gemeinsam, oder deaktiviere den anderen Dienst.
- **Client meldet Verbindung fehlgeschlagen:** Blender muss geöffnet und das Add-on aktiviert sein; in der ChatGPT-Seitenleiste muss `läuft` stehen.
- **Kritischer Aufruf hängt:** Im Blender-Tab `ChatGPT` die wartende Freigabe genehmigen oder ablehnen. Nach 170 Sekunden verfällt eine Freigabe.
- **Python-Aufruf wird abgelehnt:** Die Option `Python-Skripte zulassen` muss ausdrücklich in den Add-on-Präferenzen eingeschaltet sein; jede Ausführung verlangt weiterhin Freigabe.

## Status

**Version 1.0.0 – lokale Implementierung, nicht als vollständig end-to-end in Blender 5.2.2 getestet.** Syntax- und MCP-Protokoll-Selbsttests sind enthalten. Da Blender in dieser Erstellungsumgebung nicht ausgeführt werden kann, muss der Live-Test mit der installierten Blender-Version lokal erfolgen.

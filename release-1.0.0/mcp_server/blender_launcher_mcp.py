#!/usr/bin/env python3
"""Windows-only local MCP launcher for Blender. Does not execute Blender scripts."""
from __future__ import annotations
import csv
import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SERVER_NAME = "blender-launcher-local"
SERVER_VERSION = "0.1.0"
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 9877
MAX_LINE_BYTES = 1_000_000
VERSIONS = {"2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_launcher_status",
        "description": "Read-only status check: finds Blender in common Windows install paths, checks running processes, and probes the local Blender Bridge at 127.0.0.1:9877. Does not launch anything.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}
    },
    {
        "name": "find_blender_installations",
        "description": "Find Blender executables in common Windows install paths. Does not launch anything. Optional environment variable BLENDER_EXECUTABLE must point to a real file named blender.exe.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}
    },
    {
        "name": "start_blender",
        "description": "Launch the Blender GUI only after the user explicitly asks to start Blender. Requires confirm=true. Does not accept arbitrary command arguments, execute scripts, or open project files. Refuses to launch a duplicate if Blender is already running.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "confirm": {"type": "boolean", "description": "Must be true after an explicit user request to start Blender."}
            },
            "required": ["confirm"],
            "additionalProperties": False
        }
    }
]


def _windows_only() -> None:
    if os.name != "nt":
        raise RuntimeError("Dieser Launcher ist für Windows ausgelegt.")


def _candidate_paths() -> list[Path]:
    _windows_only()
    override = os.environ.get("BLENDER_EXECUTABLE", "").strip().strip('"')
    if override:
        path = Path(os.path.expandvars(override)).expanduser()
        if path.name.lower() != "blender.exe":
            raise RuntimeError("BLENDER_EXECUTABLE muss auf eine Datei namens blender.exe zeigen.")
        if not path.is_file():
            raise FileNotFoundError(f"BLENDER_EXECUTABLE existiert nicht: {path}")
        return [path.resolve()]

    roots: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(env_name):
            roots.append(Path(os.environ[env_name]))
    if os.environ.get("LOCALAPPDATA"):
        roots.append(Path(os.environ["LOCALAPPDATA"]) / "Programs")
    roots.append(Path.home() / "Programs")

    paths: list[Path] = []
    for root in roots:
        for version in ("5.2", "5.1", "5.0", "4.5", "4.4", "4.3", "4.2"):
            paths.append(root / "Blender Foundation" / f"Blender {version}" / "blender.exe")
        paths.append(root / "Blender Foundation" / "Blender" / "blender.exe")
    if os.environ.get("ProgramFiles(x86)"):
        paths.append(Path(os.environ["ProgramFiles(x86)"]) / "Steam" / "steamapps" / "common" / "Blender" / "blender.exe")

    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(str(path))
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def _find_installations() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for path in _candidate_paths():
        try:
            if path.is_file() and path.name.lower() == "blender.exe":
                resolved = path.resolve()
                key = os.path.normcase(str(resolved))
                if key not in seen:
                    found.append(resolved)
                    seen.add(key)
        except OSError:
            continue
    return found


def _blender_pids() -> tuple[list[int] | None, str | None]:
    _windows_only()
    tasklist = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tasklist.exe"
    if not tasklist.is_file():
        return None, f"tasklist.exe nicht gefunden: {tasklist}"
    try:
        result = subprocess.run(
            [str(tasklist), "/FI", "IMAGENAME eq blender.exe", "/FO", "CSV", "/NH"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=5, check=False,
            shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"Prozessstatus nicht prüfbar: {type(exc).__name__}"
    if result.returncode != 0:
        return None, "Windows tasklist konnte den Prozessstatus nicht zuverlässig prüfen."
    pids: list[int] = []
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) >= 2 and row[0].strip().lower() == "blender.exe":
            try:
                pids.append(int(row[1].strip()))
            except ValueError:
                pass
    return pids, None


def _probe_bridge() -> dict[str, Any]:
    payload = json.dumps({"tool": "get_status", "arguments": {}}, separators=(",", ":")).encode("utf-8") + b"\n"
    try:
        with socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=0.4) as conn:
            conn.settimeout(1.0)
            conn.sendall(payload)
            chunks = bytearray()
            while not chunks.endswith(b"\n"):
                part = conn.recv(65536)
                if not part:
                    raise ConnectionError("Bridge hat die Verbindung geschlossen.")
                chunks.extend(part)
                if len(chunks) > MAX_LINE_BYTES:
                    raise ValueError("Bridge-Antwort überschreitet das Größenlimit.")
        response = json.loads(chunks.decode("utf-8"))
        if not isinstance(response, dict):
            raise ValueError("Bridge-Antwort ist kein JSON-Objekt.")
        return {"reachable": True, "response": response}
    except (OSError, ValueError, json.JSONDecodeError, ConnectionError) as exc:
        return {"reachable": False, "message": f"{type(exc).__name__}: {exc}"}


def _status() -> dict[str, Any]:
    _windows_only()
    installations = _find_installations()
    pids, process_error = _blender_pids()
    bridge = _probe_bridge()
    return {
        "platform": "windows",
        "server": SERVER_NAME,
        "blender_installations": [str(p) for p in installations],
        "blender_running": bool(pids) if pids is not None else None,
        "blender_pids": pids,
        "process_check_error": process_error,
        "bridge_host": BRIDGE_HOST,
        "bridge_port": BRIDGE_PORT,
        "bridge_reachable": bridge["reachable"],
        "bridge_probe": bridge.get("response") if bridge["reachable"] else None,
        "bridge_probe_error": bridge.get("message")
    }


def _start_blender(arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments.get("confirm") is not True:
        raise PermissionError("Nicht gestartet. Nur nach ausdrücklicher Nutzeranfrage mit confirm=true aufrufen.")
    _windows_only()

    bridge = _probe_bridge()
    if bridge["reachable"]:
        pids, _ = _blender_pids()
        return {
            "started": False, "already_running": True, "bridge_reachable": True,
            "blender_pids": pids, "bridge_response": bridge.get("response"),
            "message": "Blender und Bridge antworten bereits; kein zweiter Prozess gestartet."
        }

    pids, process_error = _blender_pids()
    if pids is None:
        raise RuntimeError("Doppelstart kann nicht sicher ausgeschlossen werden. " + (process_error or ""))
    if pids:
        return {
            "started": False, "already_running": True, "bridge_reachable": False, "blender_pids": pids,
            "message": "Blender läuft bereits, aber die Bridge antwortet nicht. Kein zweites Fenster gestartet. Aktiviere oder prüfe das Add-on in Blender."
        }

    installations = _find_installations()
    if not installations:
        raise FileNotFoundError(
            "Blender wurde nicht an den üblichen Installationsorten gefunden. "
            "Setze BLENDER_EXECUTABLE in der MCP-Konfiguration auf den vollständigen Pfad zu deiner vertrauenswürdigen blender.exe."
        )

    executable = installations[0]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    try:
        process = subprocess.Popen(
            [str(executable)], cwd=str(executable.parent), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
            shell=False, creationflags=flags
        )
    except OSError as exc:
        raise RuntimeError(f"Blender konnte nicht gestartet werden ({type(exc).__name__}): {exc}") from exc

    time.sleep(0.8)
    bridge_after = _probe_bridge()
    return {
        "started": True, "pid": process.pid, "executable": str(executable),
        "bridge_reachable": bridge_after["reachable"],
        "bridge_probe": bridge_after.get("response") if bridge_after["reachable"] else None,
        "message": (
            "Blender-Prozess gestartet und Bridge antwortet."
            if bridge_after["reachable"]
            else "Blender-Prozess gestartet. Die Bridge antwortet noch nicht; Blender kann noch laden oder das Add-on muss aktiviert werden. Rufe den Status erneut ab."
        )
    }


def _result(value: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2, default=str)}],
        "structuredContent": value
    }
    if is_error:
        data["isError"] = True
    return data


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Request muss ein JSON-Objekt sein."}}
    request_id = message.get("id")
    if "id" not in message:
        return None
    method = message.get("method")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "params muss ein JSON-Objekt sein."}}
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in VERSIONS else "2025-11-25"
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Windows local Blender launcher. Use start_blender only after an explicit user request "
                "and with confirm=true. Does not execute scripts, accept arbitrary commands, or open files. "
                "Bridge probe is a read-only get_status request to 127.0.0.1:9877."
            )
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "arguments muss ein JSON-Objekt sein."}}
        try:
            if name == "get_launcher_status":
                value = _status()
            elif name == "find_blender_installations":
                _windows_only()
                value = {"installations": [str(p) for p in _find_installations()], "launched": False}
            elif name == "start_blender":
                value = _start_blender(arguments)
            else:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": f"Unbekanntes Tool: {name}"}}
            return {"jsonrpc": "2.0", "id": request_id, "result": _result(value)}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": request_id, "result": _result({"error_type": type(exc).__name__, "error": str(exc)}, True)}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Nicht unterstützte MCP-Methode: {method}"}}


def main() -> int:
    for raw in sys.stdin.buffer:
        if len(raw) > MAX_LINE_BYTES:
            print("Blender Launcher MCP: Request zu groß; übersprungen.", file=sys.stderr)
            continue
        request: Any = None
        try:
            request = json.loads(raw.decode("utf-8"))
            response = _handle(request)
        except Exception as exc:
            request_id = request.get("id") if isinstance(request, dict) else None
            response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": f"Interner Fehler: {type(exc).__name__}: {exc}"}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

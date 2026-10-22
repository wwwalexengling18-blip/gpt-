#!/usr/bin/env python3
"""Dependency-free stdio MCP server for the local ChatGPT Blender Bridge add-on.

The server never imports bpy. It forwards tool calls to the Blender add-on over
127.0.0.1 TCP, while stdout is reserved exclusively for MCP JSON-RPC messages.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import Any

HOST = "127.0.0.1"
PORT = 9877
SOCKET_TIMEOUT = 190
MAX_LINE_BYTES = 2_000_000
PROTOCOL_VERSIONS = {
    "2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"
}


def _load_tools() -> list[dict[str, Any]]:
    schema_path = Path(__file__).with_name("tool_schemas.json")
    with schema_path.open("r", encoding="utf-8") as handle:
        tools = json.load(handle)
    if not isinstance(tools, list) or not tools:
        raise RuntimeError("tool_schemas.json ist leer oder ungültig")
    return tools


try:
    TOOLS = _load_tools()
except Exception as exc:  # Keep stderr useful but do not pollute MCP stdout.
    print(f"ChatGPT Blender Bridge: Tool-Schema konnte nicht geladen werden: {exc}", file=sys.stderr)
    TOOLS = []
TOOL_NAMES = {item.get("name") for item in TOOLS}


def _send_to_blender(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"tool": tool, "arguments": arguments}, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    with socket.create_connection((HOST, PORT), timeout=SOCKET_TIMEOUT) as sock:
        sock.settimeout(SOCKET_TIMEOUT)
        sock.sendall(payload)
        chunks = bytearray()
        while not chunks.endswith(b"\n"):
            part = sock.recv(65536)
            if not part:
                raise ConnectionError("Blender hat die Verbindung ohne Antwort geschlossen.")
            chunks.extend(part)
            if len(chunks) > MAX_LINE_BYTES:
                raise ValueError("Antwort von Blender überschreitet die Größenbegrenzung.")
    try:
        result = json.loads(chunks.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ungültige JSON-Antwort von Blender: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError("Blender-Antwort ist kein JSON-Objekt.")
    return result


def _jsonrpc_error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    # Notifications have no response.
    if "id" not in message:
        return None

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else "2025-11-25"
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "chatgpt-blender-bridge", "version": "1.0.0"},
                "instructions": (
                    "Controls a local Blender instance through an add-on bound only to 127.0.0.1. "
                    "Critical actions may wait for an explicit approval in Blender's ChatGPT sidebar. "
                    "Python execution is disabled until enabled in the add-on preferences."
                ),
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in TOOL_NAMES:
            return _jsonrpc_error(request_id, -32602, f"Unbekanntes Tool: {name}")
        if not isinstance(arguments, dict):
            return _jsonrpc_error(request_id, -32602, "arguments muss ein JSON-Objekt sein")
        try:
            forwarded = _send_to_blender(str(name), arguments)
        except Exception as exc:
            details = (
                f"{type(exc).__name__}: {exc}. Prüfe, ob Blender geöffnet ist, "
                f"das Add-on aktiviert wurde und 127.0.0.1:{PORT} in Blender als laufend angezeigt wird."
            )
            return {
                "jsonrpc": "2.0", "id": request_id,
                "result": {"content": [{"type": "text", "text": details}], "isError": True},
            }
        if forwarded.get("ok"):
            value = forwarded.get("result")
            try:
                rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
            except Exception:
                rendered = str(value)
            return {
                "jsonrpc": "2.0", "id": request_id,
                "result": {"content": [{"type": "text", "text": rendered}], "structuredContent": value},
            }
        detail = forwarded.get("error", "Unbekannter Fehler in Blender")
        if forwarded.get("traceback"):
            detail += "\n" + forwarded["traceback"]
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {"content": [{"type": "text", "text": detail}], "isError": True},
        }

    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}

    return _jsonrpc_error(request_id, -32601, f"Methode nicht unterstützt: {method}")


def main() -> int:
    if not TOOLS:
        print("ChatGPT Blender Bridge: tool_schemas.json fehlt oder ist ungültig", file=sys.stderr)
        return 2
    for raw in sys.stdin.buffer:
        message = None
        if len(raw) > MAX_LINE_BYTES:
            print("ChatGPT Blender Bridge: MCP-Nachricht zu groß", file=sys.stderr)
            continue
        try:
            message = json.loads(raw.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError("MCP-Nachricht muss ein JSON-Objekt sein")
            response = _handle(message)
        except Exception as exc:
            request_id = message.get("id") if isinstance(message, dict) else None
            response = _jsonrpc_error(request_id, -32603, f"Interner Fehler: {type(exc).__name__}: {exc}")
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

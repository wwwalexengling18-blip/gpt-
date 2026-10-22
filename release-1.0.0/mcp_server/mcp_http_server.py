#!/usr/bin/env python3
"""Optional Streamable HTTP MCP endpoint for use through an authenticated tunnel.

It binds to 127.0.0.1 only. Do not change that to 0.0.0.0. A secure tunnel or
reverse proxy with TLS should be used for remote ChatGPT/client access.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import mcp_bridge_server as bridge

SUPPORTED_HTTP_VERSIONS = {"2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26"}
MAX_BODY = 2_000_000
DEFAULT_PORT = 8765


def _origins() -> set[str]:
    value = os.environ.get(
        "BLENDER_MCP_ALLOWED_ORIGINS",
        "https://chatgpt.com,https://chat.openai.com,http://localhost,http://127.0.0.1",
    )
    return {item.strip().rstrip("/") for item in value.split(",") if item.strip()}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class MCPHandler(BaseHTTPRequestHandler):
    server_version = "ChatGPTBlenderBridgeHTTP/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        # HTTP access logs go to stderr, never to an MCP response channel.
        print("[Blender MCP HTTP] " + (fmt % args), file=sys.stderr)

    def _send_json(self, status: int, payload: dict[str, Any] | None, allow_origin: str | None = None) -> None:
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if allow_origin:
            self.send_header("Access-Control-Allow-Origin", allow_origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _security_check(self) -> tuple[bool, int, str, str | None]:
        origin = self.headers.get("Origin")
        normalized_origin = origin.rstrip("/") if origin else None
        if normalized_origin and normalized_origin not in _origins():
            return False, 403, "Origin nicht erlaubt.", None
        token = os.environ.get("BLENDER_MCP_HTTP_TOKEN", "")
        auth = self.headers.get("Authorization", "")
        supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
        if not token or not supplied or not secrets.compare_digest(supplied, token):
            return False, 401, "Unauthorized: gültigen Bearer-Token setzen.", normalized_origin
        return True, 200, "", normalized_origin

    def do_OPTIONS(self) -> None:
        ok, status, message, origin = self._security_check()
        if not ok:
            self._send_json(status, {"error": message}, origin)
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin or "null")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Accept, MCP-Protocol-Version, Mcp-Method, Mcp-Name")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        self.send_error(405, "MCP Streamable HTTP endpoint accepts POST only")

    def do_DELETE(self) -> None:
        self.send_error(405, "MCP sessions are not used")

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/mcp":
            self._send_json(404, {"error": "Use endpoint /mcp"})
            return
        ok, status, message, origin = self._security_check()
        if not ok:
            self._send_json(status, {"error": message}, origin)
            return
        if "application/json" not in self.headers.get("Content-Type", "").lower():
            self._send_json(415, {"error": "Content-Type muss application/json sein."}, origin)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Ungültiger Content-Length."}, origin)
            return
        if length <= 0 or length > MAX_BODY:
            self._send_json(413 if length > MAX_BODY else 400, {"error": "Request-Größe ungültig oder zu groß."}, origin)
            return
        try:
            message_obj = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(message_obj, dict):
                raise ValueError("JSON-RPC body muss ein Objekt sein.")
        except Exception as exc:
            self._send_json(400, _error_response(None, -32700, f"Ungültiger JSON-Body: {exc}"), origin)
            return

        method = message_obj.get("method")
        request_id = message_obj.get("id")
        params = message_obj.get("params") or {}
        meta = params.get("_meta") if isinstance(params, dict) else None
        meta_version = meta.get("io.modelcontextprotocol/protocolVersion") if isinstance(meta, dict) else None
        header_version = self.headers.get("MCP-Protocol-Version")
        modern = bool(meta_version or header_version)

        # Latest MCP HTTP revisions require per-request protocol metadata and matching headers.
        if modern:
            if not header_version or not meta_version or header_version != meta_version:
                self._send_json(400, _error_response(request_id, -32020, "HeaderMismatch: MCP-Protocol-Version fehlt oder stimmt nicht mit params._meta überein."), origin)
                return
            if header_version not in SUPPORTED_HTTP_VERSIONS:
                self._send_json(400, _error_response(request_id, -32015, f"UnsupportedProtocolVersionError: unterstützt werden {sorted(SUPPORTED_HTTP_VERSIONS)}"), origin)
                return
            if "id" in message_obj:
                if self.headers.get("Mcp-Method") != method:
                    self._send_json(400, _error_response(request_id, -32020, "HeaderMismatch: Mcp-Method fehlt oder passt nicht zum JSON-RPC method."), origin)
                    return
                expected_name = None
                if method == "tools/call":
                    expected_name = params.get("name") if isinstance(params, dict) else None
                elif method == "resources/read":
                    expected_name = params.get("uri") if isinstance(params, dict) else None
                elif method == "prompts/get":
                    expected_name = params.get("name") if isinstance(params, dict) else None
                if expected_name is not None and self.headers.get("Mcp-Name") != str(expected_name):
                    self._send_json(400, _error_response(request_id, -32020, "HeaderMismatch: Mcp-Name fehlt oder passt nicht zum params-Namen."), origin)
                    return
            if method == "initialize" and isinstance(params, dict):
                # The shared protocol handler uses the legacy initialize field; map the modern header version into it.
                params = dict(params)
                params["protocolVersion"] = header_version
                message_obj["params"] = params

        # HTTP requests use the same tool dispatch logic as stdio MCP.
        try:
            response = bridge._handle(message_obj)
        except Exception as exc:
            response = _error_response(request_id, -32603, f"Interner Serverfehler: {type(exc).__name__}: {exc}")

        if response is None:
            self._send_json(202, None, origin)
            return
        self._send_json(200, response, origin)


def main() -> int:
    parser = argparse.ArgumentParser(description="Authenticated local Streamable HTTP MCP endpoint for Blender")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port muss zwischen 1024 und 65535 liegen")
    if not os.environ.get("BLENDER_MCP_HTTP_TOKEN"):
        token = secrets.token_urlsafe(32)
        os.environ["BLENDER_MCP_HTTP_TOKEN"] = token
        print("[Blender MCP HTTP] Generierter Token (für diese Sitzung): " + token, file=sys.stderr)
        print("[Blender MCP HTTP] Für Wiederverwendung BLENDER_MCP_HTTP_TOKEN als Umgebungsvariable setzen.", file=sys.stderr)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), MCPHandler)
    server.daemon_threads = True
    print(f"[Blender MCP HTTP] Aktiv auf http://127.0.0.1:{args.port}/mcp (nur localhost)", file=sys.stderr)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

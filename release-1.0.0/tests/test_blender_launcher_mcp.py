"""Non-destructive protocol tests for blender_launcher_mcp.py."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "mcp_server" / "blender_launcher_mcp.py"
SPEC = importlib.util.spec_from_file_location("blender_launcher_mcp", MODULE_PATH)
assert SPEC and SPEC.loader
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LauncherProtocolTests(unittest.TestCase):
    def test_initialize(self):
        response = launcher._handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"}
        })
        self.assertEqual(response["result"]["serverInfo"]["name"], "blender-launcher-local")
        self.assertEqual(response["result"]["protocolVersion"], "2025-11-25")

    def test_tools_list(self):
        response = launcher._handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {item["name"] for item in response["result"]["tools"]}
        self.assertEqual(names, {"get_launcher_status", "find_blender_installations", "start_blender"})

    def test_start_denied_without_confirmation_before_any_probe(self):
        original = {name: getattr(launcher, name) for name in ("_probe_bridge", "_blender_pids", "_windows_only")}
        try:
            launcher._probe_bridge = lambda: self.fail("Must not probe before confirmation")
            launcher._blender_pids = lambda: self.fail("Must not inspect processes before confirmation")
            launcher._windows_only = lambda: self.fail("Must not check platform before confirmation")
            response = launcher._handle({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "start_blender", "arguments": {"confirm": False}}
            })
            self.assertTrue(response["result"]["isError"])
            self.assertIn("Nicht gestartet", response["result"]["structuredContent"]["error"])
        finally:
            for name, value in original.items():
                setattr(launcher, name, value)

    def test_unknown_tool_rejected(self):
        response = launcher._handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "not_a_tool", "arguments": {}}
        })
        self.assertEqual(response["error"]["code"], -32602)

    def test_notification_has_no_response(self):
        self.assertIsNone(launcher._handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))


if __name__ == "__main__":
    unittest.main()

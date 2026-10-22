import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp_server" / "mcp_bridge_server.py"


class MCPProtocolTests(unittest.TestCase):
    def test_stdio_basics_and_tools_catalog(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            {"jsonrpc": "2.0", "id": 4, "method": "method/does-not-exist"},
        ]
        wire = "".join(json.dumps(req) + "\n" for req in requests)
        result = subprocess.run(
            [sys.executable, str(SERVER)], input=wire, text=True,
            capture_output=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual([item.get("id") for item in replies], [1, 2, 3, 4])
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-11-25")
        tools = replies[1]["result"]["tools"]
        self.assertGreaterEqual(len(tools), 15)
        names = {tool["name"] for tool in tools}
        self.assertIn("scene_overview", names)
        self.assertIn("repair_scene", names)
        self.assertIn("execute_python", names)
        self.assertEqual(replies[2]["result"], {})
        self.assertEqual(replies[3]["error"]["code"], -32601)

    def test_call_without_blender_returns_actionable_error(self):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "scene_overview", "arguments": {}}}
        result = subprocess.run(
            [sys.executable, str(SERVER)], input=json.dumps(request) + "\n",
            text=True, capture_output=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        reply = json.loads(result.stdout.splitlines()[0])
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("Blender", reply["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()

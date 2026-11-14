import json
import sys
import tempfile
import unittest
from pathlib import Path

from mcp_token_audit.config import Server, _mini_toml, discover, from_file
from mcp_token_audit.probe import probe, tool_cost

FAKE = str(Path(__file__).with_name("fake_server.py"))


class ConfigTests(unittest.TestCase):
    def test_discover_all_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, home = Path(tmp, "proj"), Path(tmp, "home")
            (root / ".cursor").mkdir(parents=True)
            (home / ".codex").mkdir(parents=True)
            (home / ".gemini").mkdir(parents=True)
            (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"a": {"command": "npx", "args": ["-y", "a"]}}}))
            (root / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"b": {"url": "https://x/mcp"}}}))
            (home / ".gemini" / "settings.json").write_text(json.dumps({"mcpServers": {"c": {"httpUrl": "https://y"}}}))
            (home / ".claude.json").write_text(json.dumps({
                "mcpServers": {"d": {"command": "d"}},
                "projects": {str(root.resolve()): {"mcpServers": {"e": {"command": "e", "disabled": True}}}}}))
            (home / ".codex" / "config.toml").write_text(
                'model = "x"\n[mcp_servers.f]\ncommand = "uvx"\nargs = ["f-mcp"]\n[mcp_servers.f.env]\nK = "1"\n')
            servers = {s.name: s for s in discover(root, home)}
        self.assertEqual(sorted(servers), list("abcdef"))
        self.assertEqual(servers["b"].transport, "http")
        self.assertEqual(servers["c"].url, "https://y")
        self.assertTrue(servers["e"].disabled)
        self.assertEqual(servers["f"].args, ["f-mcp"])
        self.assertEqual(servers["f"].env, {"K": "1"})

    def test_mini_toml(self):
        data = _mini_toml('[mcp_servers."my srv"]\ncommand = "node"\nargs = ["s.js", "--x"]\nenabled = false\n')
        self.assertEqual(data["mcp_servers"]["my srv"]["args"], ["s.js", "--x"])
        self.assertIs(data["mcp_servers"]["my srv"]["enabled"], False)


class ProbeTests(unittest.TestCase):
    def test_stdio_probe_with_pagination(self):
        r = probe(Server("fake", "test", command=sys.executable, args=[FAKE]), timeout=15)
        self.assertTrue(r.ok, r.error)
        self.assertEqual([t["name"] for t in r.tools], ["search_docs", "ping", "page_two_tool"])
        self.assertEqual(len(r.prompts), 1)
        names = [n for n, _ in r.tool_tokens()]
        self.assertEqual(names[0], "search_docs")
        self.assertGreater(r.tokens, 100)

    def test_missing_command(self):
        r = probe(Server("nope", "test", command="definitely-not-a-real-command-xyz"), timeout=3)
        self.assertFalse(r.ok)
        self.assertTrue(r.error)

    def test_tool_cost(self):
        small = tool_cost({"name": "a", "description": "b"})
        big = tool_cost({"name": "a", "description": "b" * 4000})
        self.assertLess(small, 30)
        self.assertGreater(big, 900)

    def test_cli_config_and_tools_json(self):
        from mcp_token_audit import cli
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp, "mcp.json")
            cfg.write_text(json.dumps({"mcpServers": {"fake": {"command": sys.executable, "args": [FAKE]}}}))
            self.assertEqual(cli.main(["--config", str(cfg), "--json"]), 0)
            self.assertEqual(cli.main(["--config", str(cfg), "--dry-run"]), 0)
            saved = Path(tmp, "tools.json")
            saved.write_text(json.dumps({"tools": [{"name": "x", "description": "y", "inputSchema": {}}]}))
            self.assertEqual(cli.main(["--tools-json", str(saved)]), 0)
            self.assertEqual(len(from_file(cfg)), 1)


if __name__ == "__main__":
    unittest.main()

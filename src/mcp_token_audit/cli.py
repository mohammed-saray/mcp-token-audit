"""mcp-token-audit command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from .config import Server, discover, from_file
from .probe import Result, probe, tool_cost
from .tokens import method


def _bar(n: int, top: int, width: int = 20) -> str:
    return "█" * max(1, round(width * n / top)) if top and n else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mcp-token-audit", description="Start each configured MCP server, list its "
                                 "tools, and estimate how many tokens their definitions add to every request.")
    ap.add_argument("--dir", default=".", help="project root used to find project configs (default: .)")
    ap.add_argument("--config", action="append", default=[], help="audit this config file instead (repeatable)")
    ap.add_argument("--tools-json", help="audit a saved tools/list result (JSON) without starting anything")
    ap.add_argument("--only", action="append", default=[], help="only these server names (repeatable)")
    ap.add_argument("--include-disabled", action="store_true")
    ap.add_argument("--timeout", type=float, default=25, help="seconds per server (default 25)")
    ap.add_argument("--top", type=int, default=3, help="biggest tools to show per server")
    ap.add_argument("--dry-run", action="store_true", help="only list what would be started")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--version", action="version", version=f"mcp-token-audit {__version__}")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if a.tools_json:
        data = json.loads(Path(a.tools_json).read_text(encoding="utf-8"))
        tools = data.get("tools", data.get("result", {}).get("tools", [])) if isinstance(data, dict) else data
        r = Result(Server(Path(a.tools_json).stem, a.tools_json), ok=True, tools=tools)
        results = [r]
    else:
        servers = [s for c in a.config for s in from_file(Path(c))] if a.config else discover(Path(a.dir))
        # same server configured in several tools -> probe once
        uniq, seen = [], {}
        for s in servers:
            key = (s.command, tuple(s.args), s.url)
            if key in seen:
                seen[key].source += f", {s.source}"
                continue
            seen[key] = s
            uniq.append(s)
        servers = [s for s in uniq if (not a.only or s.name in a.only) and (a.include_disabled or not s.disabled)]
        if not servers:
            print("No MCP servers found. Looked in .mcp.json, Claude Desktop claude_desktop_config.json, "
                  "~/.claude.json, ~/.codex/config.toml, "
                  ".gemini/settings.json, .cursor/mcp.json, .vscode/mcp.json.")
            return 0
        if a.dry_run:
            for s in servers:
                target = s.url or " ".join([s.command or "?", *s.args])
                print(f"{s.name:<24} {s.transport:<6} {target}   [{s.source}]")
            return 0
        print(f"Probing {len(servers)} MCP server(s)…", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=min(8, len(servers))) as pool:
            results = list(pool.map(lambda s: probe(s, a.timeout), servers))

    ok = [r for r in results if r.ok]
    total = sum(r.tokens for r in ok)
    if a.json:
        print(json.dumps({"estimator": method(), "total_tokens": total, "servers": [{
            "name": r.server.name, "source": r.server.source, "transport": r.server.transport, "ok": r.ok,
            "error": r.error or None, "tools": len(r.tools), "tokens": r.tokens, "prompts": len(r.prompts),
            "tool_tokens": dict(r.tool_tokens()), "seconds": round(r.seconds, 2)} for r in results]}, indent=2))
        return 0

    top = max((r.tokens for r in ok), default=0)
    print(f"\n{'server':<24}{'tools':>6}{'tokens':>9}  ")
    print("─" * 62)
    for r in sorted(results, key=lambda r: -r.tokens):
        if r.ok:
            print(f"{r.server.name[:23]:<24}{len(r.tools):>6}{r.tokens:>9}  {_bar(r.tokens, top)}")
            for name, cost in r.tool_tokens()[:a.top]:
                print(f"{'':<4}↳ {name[:40]:<40}{cost:>7}")
        else:
            print(f"{r.server.name[:23]:<24}{'—':>6}{'—':>9}  ✗ {r.error[:60]}")
    print("─" * 62)
    print(f"{'total':<24}{sum(len(r.tools) for r in ok):>6}{total:>9}")
    print(f"\n≈ {total:,} tokens of tool definitions go out with every request while all of these are enabled.")
    if ok and total > 10000:
        biggest = max(ok, key=lambda r: r.tokens)
        print(f"Tip: disable servers you don't use in this project. '{biggest.server.name}' alone costs "
              f"≈ {biggest.tokens:,} tokens. Clients with deferred/lazy tool loading (e.g. Claude Code tool search) "
              "pay much less up front.")
    print(f"Estimator: {method()}.")
    return 0 if ok or not results else 1


if __name__ == "__main__":
    sys.exit(main())

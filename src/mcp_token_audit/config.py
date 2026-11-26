"""Find MCP server definitions in Claude, Codex, Gemini CLI, Cursor and VS Code configs."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


@dataclass
class Server:
    name: str
    source: str
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    disabled: bool = False

    @property
    def transport(self) -> str:
        return "http" if self.url else "stdio"


def _from_mapping(servers: dict, source: str) -> List[Server]:
    out = []
    for name, cfg in (servers or {}).items():
        if not isinstance(cfg, dict):
            continue
        url = cfg.get("url") or cfg.get("httpUrl") or cfg.get("serverUrl")
        out.append(Server(
            name=name, source=source, command=cfg.get("command"),
            args=[str(a) for a in cfg.get("args") or []],
            env={k: str(v) for k, v in (cfg.get("env") or {}).items()},
            url=url, headers={k: str(v) for k, v in (cfg.get("headers") or cfg.get("http_headers") or {}).items()},
            disabled=bool(cfg.get("disabled") or cfg.get("enabled") is False),
        ))
    return out


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _toml(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if tomllib:
        try:
            return tomllib.loads(text)
        except Exception:
            return None
    return _mini_toml(text)


def _mini_toml(text: str) -> dict:
    """Tiny fallback parser good enough for [mcp_servers.x] tables on Python < 3.11."""
    root: dict = {}
    cur = root
    for raw in text.splitlines():
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\[([^\]]+)\]$", line)
        if m:
            cur = root
            for part in re.findall(r'"[^"]+"|[^.]+', m.group(1)):
                cur = cur.setdefault(part.strip('"'), {})
            continue
        m = re.match(r'^("?[\w.-]+"?)\s*=\s*(.+)$', line)
        if m:
            key, val = m.group(1).strip('"'), m.group(2).strip()
            try:
                cur[key] = json.loads(val.replace("'", '"')) if val[0] in '["{' or val[0].isdigit() \
                    else (val == "true" if val in ("true", "false") else val.strip("'\""))
            except ValueError:
                cur[key] = val.strip("'\"")
    return root


def discover(root: Path, home: Optional[Path] = None) -> List[Server]:
    home = home or Path.home()
    root = root.resolve()
    found: List[Server] = []
    claude_desktop = (home / "AppData" / "Roaming" / "Claude" if sys.platform == "win32" else
                      home / "Library" / "Application Support" / "Claude" if sys.platform == "darwin" else
                      home / ".config" / "Claude") / "claude_desktop_config.json"
    for path, label in ((root / ".mcp.json", "Claude Code (project .mcp.json)"),
                        (claude_desktop, "Claude Desktop"),
                        (root / ".cursor" / "mcp.json", "Cursor (project)"),
                        (home / ".cursor" / "mcp.json", "Cursor (global)"),
                        (root / ".gemini" / "settings.json", "Gemini CLI (project)"),
                        (home / ".gemini" / "settings.json", "Gemini CLI (global)")):
        data = _json(path)
        if isinstance(data, dict):
            found += _from_mapping(data.get("mcpServers"), label)
    vscode = _json(root / ".vscode" / "mcp.json")
    if isinstance(vscode, dict):
        found += _from_mapping(vscode.get("servers"), "VS Code (project)")
    claude = _json(home / ".claude.json")
    if isinstance(claude, dict):
        found += _from_mapping(claude.get("mcpServers"), "Claude Code (user)")
        proj = (claude.get("projects") or {})
        for key, val in proj.items():
            try:
                same = Path(key).resolve() == root
            except OSError:
                same = False
            if same and isinstance(val, dict):
                found += _from_mapping(val.get("mcpServers"), "Claude Code (local)")
    codex = _toml(home / ".codex" / "config.toml")
    if isinstance(codex, dict):
        found += _from_mapping(codex.get("mcp_servers"), "Codex CLI")
    return found


def from_file(path: Path) -> List[Server]:
    data = _json(path) if path.suffix != ".toml" else _toml(path)
    if not isinstance(data, dict):
        return []
    mapping = data.get("mcpServers") or data.get("servers") or data.get("mcp_servers") or {}
    return _from_mapping(mapping, str(path))

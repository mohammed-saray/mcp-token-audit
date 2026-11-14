"""Talk just enough MCP (JSON-RPC 2.0) to list a server's tools, prompts and resources."""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

from .config import Server
from .tokens import estimate

PROTOCOL = "2025-06-18"
CLIENT = {"name": "mcp-token-audit", "version": "0.1.0"}


@dataclass
class Result:
    server: Server
    ok: bool = False
    error: str = ""
    tools: List[dict] = field(default_factory=list)
    prompts: List[dict] = field(default_factory=list)
    seconds: float = 0.0

    def tool_tokens(self) -> List[tuple]:
        return sorted(((t.get("name", "?"), tool_cost(t)) for t in self.tools), key=lambda x: -x[1])

    @property
    def tokens(self) -> int:
        return sum(c for _, c in self.tool_tokens())


def tool_cost(tool: dict) -> int:
    """Tokens for one tool as a client sends it to the model: name + description + JSON schema."""
    shaped = {"name": tool.get("name"), "description": tool.get("description", ""),
              "input_schema": tool.get("inputSchema") or tool.get("input_schema") or {}}
    return estimate(json.dumps(shaped, ensure_ascii=False, separators=(",", ":")))


# --------------------------------------------------------------------------- stdio

class StdioClient:
    def __init__(self, server: Server, timeout: float):
        cmd = server.command
        if not cmd:
            raise RuntimeError("no command")
        exe = shutil.which(cmd) or cmd
        argv = [exe, *server.args]
        if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
            argv = ["cmd", "/c", *argv]
        env = dict(os.environ)
        env.update({k: os.path.expandvars(v) for k, v in server.env.items()})
        self.timeout = timeout
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, env=env)
        self.q: "queue.Queue[Optional[dict]]" = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.next_id = 1

    def _reader(self):
        for raw in self.proc.stdout:  # type: ignore[union-attr]
            try:
                self.q.put(json.loads(raw.decode("utf-8", errors="replace")))
            except ValueError:
                continue  # servers sometimes print banners to stdout
        self.q.put(None)

    def send(self, msg: dict):
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())  # type: ignore[union-attr]
        self.proc.stdin.flush()  # type: ignore[union-attr]

    def request(self, method: str, params: Optional[dict] = None) -> dict:
        rid = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"{method} timed out after {self.timeout:g}s")
            try:
                msg = self.q.get(timeout=left)
            except queue.Empty:
                continue
            if msg is None:
                raise RuntimeError("server exited")
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", str(msg["error"])))
                return msg.get("result") or {}
            if "method" in msg and "id" in msg:  # server->client request (e.g. roots/list): decline politely
                self.send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported"}})

    def notify(self, method: str):
        self.send({"jsonrpc": "2.0", "method": method, "params": {}})

    def close(self):
        try:
            self.proc.stdin.close()  # type: ignore[union-attr]
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


# --------------------------------------------------------------------------- http

class HttpClient:
    def __init__(self, server: Server, timeout: float):
        self.url, self.timeout = server.url, timeout
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                        **{k: os.path.expandvars(v) for k, v in server.headers.items()}}
        self.next_id = 1

    def _post(self, msg: dict) -> Optional[dict]:
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode(), headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.headers["Mcp-Session-Id"] = sid
                body = resp.read().decode("utf-8", errors="replace")
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError(f"needs authentication (HTTP {e.code}) — add headers in your config") from None
            raise RuntimeError(f"HTTP {e.code}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"unreachable: {e.reason}") from None
        if "id" not in msg:
            return None
        msgs = []
        if "text/event-stream" in ctype:
            for line in body.splitlines():
                if line.startswith("data:"):
                    try:
                        msgs.append(json.loads(line[5:].strip()))
                    except ValueError:
                        pass
        elif body.strip():
            data = json.loads(body)
            msgs = data if isinstance(data, list) else [data]
        for m in msgs:
            if m.get("id") == msg["id"]:
                if "error" in m:
                    raise RuntimeError(m["error"].get("message", str(m["error"])))
                return m.get("result") or {}
        raise RuntimeError("no response")

    def request(self, method, params=None):
        rid = self.next_id
        self.next_id += 1
        return self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})

    def notify(self, method):
        try:
            self._post({"jsonrpc": "2.0", "method": method, "params": {}})
        except RuntimeError:
            pass

    def close(self):
        pass


def _paged(client, method: str, key: str, limit: int = 50) -> List[dict]:
    items, cursor = [], None
    for _ in range(limit):
        res = client.request(method, {"cursor": cursor} if cursor else {})
        items += res.get(key) or []
        cursor = res.get("nextCursor")
        if not cursor:
            break
    return items


def probe(server: Server, timeout: float = 20.0) -> Result:
    r = Result(server)
    start = time.monotonic()
    client = None
    try:
        client = HttpClient(server, timeout) if server.url else StdioClient(server, timeout)
        init = client.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT})
        client.notify("notifications/initialized")
        caps = init.get("capabilities") or {}
        r.tools = _paged(client, "tools/list", "tools") if "tools" in caps or not caps else []
        if "prompts" in caps:
            try:
                r.prompts = _paged(client, "prompts/list", "prompts")
            except Exception:
                pass
        r.ok = True
    except FileNotFoundError:
        r.error = f"command not found: {server.command}"
    except Exception as e:  # noqa: BLE001 - report every failure per server
        r.error = str(e) or e.__class__.__name__
    finally:
        if client:
            client.close()
        r.seconds = time.monotonic() - start
    return r


if __name__ == "__main__":  # pragma: no cover
    print(probe(Server("x", "cli", command=sys.argv[1], args=sys.argv[2:])).tools)

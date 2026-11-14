"""Minimal stdio MCP server used by the tests."""
import json
import sys

print("banner line that is not json", flush=True)  # real servers sometimes do this
TOOLS = [
    {"name": "search_docs", "description": "Search the documentation. " * 20,
     "inputSchema": {"type": "object", "properties": {"q": {"type": "string", "description": "query"}}}},
    {"name": "ping", "description": "Ping.", "inputSchema": {"type": "object"}},
    {"name": "page_two_tool", "description": "Returned on the second page.", "inputSchema": {"type": "object"}},
]
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    m, rid = msg["method"], msg["id"]
    if m == "initialize":
        res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}, "prompts": {}},
               "serverInfo": {"name": "fake", "version": "1"}}
    elif m == "tools/list":
        cursor = (msg.get("params") or {}).get("cursor")
        res = {"tools": TOOLS[2:]} if cursor else {"tools": TOOLS[:2], "nextCursor": "p2"}
    elif m == "prompts/list":
        res = {"prompts": [{"name": "summarize"}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "nope"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": res}), flush=True)

# mcp-token-audit 🧾

**Every MCP server you enable adds its tool definitions to every request. This tool starts each server, lists its tools and shows you the bill in tokens.**

[![CI](https://github.com/mohammed-saray/mcp-token-audit/actions/workflows/ci.yml/badge.svg)](https://github.com/mohammed-saray/mcp-token-audit/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

```text
$ mcp-token-audit
Probing 6 MCP server(s)…

server                   tools   tokens
──────────────────────────────────────────────────────────────
github                      41    18230  ████████████████████
    ↳ create_pull_request                       1310
    ↳ search_code                                 980
    ↳ update_issue                                940
playwright                  21     6740  ███████
    ↳ browser_run_code                           720
filesystem                  14     2410  ███
context7                     2      910  █
figma                        —        —  ✗ needs authentication (HTTP 401) — add headers in your config
──────────────────────────────────────────────────────────────
total                       78    28290

≈ 28,290 tokens of tool definitions go out with every request while all of these are enabled.
Tip: disable servers you don't use in this project. 'github' alone costs ≈ 18,230 tokens.
```
<sub>Example output. Numbers depend on server versions.</sub>

## The problem

MCP makes it easy to plug tools into Claude Code, Codex CLI, Gemini CLI, Cursor
and VS Code. But the model has to *see* each tool's name, description and JSON
schema on every turn. Users report one server costing ~20K tokens per message,
and a "hi" taking 30K tokens before any work starts. That context fills up
faster, compaction kicks in sooner, and subscription limits run out earlier.

Nobody can cut a cost they can't see. `mcp-token-audit` measures it.

## Install

```bash
pipx install git+https://github.com/mohammed-saray/mcp-token-audit
```

## Usage

```bash
mcp-token-audit                       # every server configured for this project + your user configs
mcp-token-audit --dry-run             # just list what would be started (do this first!)
mcp-token-audit --only github --only playwright
mcp-token-audit --config .mcp.json    # a specific config file (repeatable)
mcp-token-audit --tools-json saved.json   # audit a saved tools/list response, starts nothing
mcp-token-audit --json                # per-tool numbers for scripts
mcp-token-audit --top 10              # show the 10 most expensive tools per server
```

## Where it looks

| Client | Config |
|---|---|
| Claude Code | `.mcp.json`, `~/.claude.json` (user + per-project `mcpServers`) |
| Codex CLI | `~/.codex/config.toml` → `[mcp_servers.*]` |
| Gemini CLI | `.gemini/settings.json`, `~/.gemini/settings.json` |
| Cursor | `.cursor/mcp.json`, `~/.cursor/mcp.json` |
| VS Code | `.vscode/mcp.json` |

A server configured in several clients is probed once.

## How it works

1. Speaks MCP's JSON-RPC directly: `initialize` → `notifications/initialized` → `tools/list` (following `nextCursor` pages) → `prompts/list`.
2. **stdio** servers are started with the command, args and env from your config, then shut down. **Streamable HTTP** servers get a POST, with SSE responses and `Mcp-Session-Id` handled.
3. Each tool is serialized the way clients send it to the model (`name` + `description` + `input_schema`) and its tokens are estimated (`tiktoken` if installed, otherwise a script-aware heuristic).
4. Servers run in parallel with a per-server timeout. A failure in one server doesn't affect the others.

## ⚠️ Safety

This **runs the commands in your MCP configs**, exactly as your AI client would.
Run `--dry-run` first and only audit configs you trust. Servers that need OAuth
show up as "needs authentication" and are skipped. The tool never sends your
data anywhere else.

## Limitations

- Token counts are estimates. Real cost also depends on how each client formats tools.
- Clients with deferred tool loading (Claude Code's tool search, for example) don't send full schemas up front, so your *actual* cost can be lower. The audit shows the worst case.
- Servers that only work after interactive login are reported, not measured.

## Roadmap

- [ ] `--compare` to diff two runs after a server upgrade
- [ ] Flag tools with huge descriptions or deeply nested schemas
- [ ] Generate a trimmed config with only the servers you pick

## Related tools in this suite

Small, dependency-free tools for people fighting AI usage limits:

| Tool | What it does |
|---|---|
| [burnrate](https://github.com/mohammed-saray/burnrate) | Forecast Claude Code / Codex limits from local logs |
| [context-diet](https://github.com/mohammed-saray/context-diet) | Find the CLAUDE.md / AGENTS.md / GEMINI.md bloat you pay for on every message |
| [ai-handoff](https://github.com/mohammed-saray/ai-handoff) | Hit a limit? Move the task to another AI with a handoff file |
| [ai-error-decoder](https://github.com/mohammed-saray/ai-error-decoder) | Explain 429 / 529 / quota errors from Anthropic, OpenAI and Gemini |
| [ratelimit-retry](https://github.com/mohammed-saray/ratelimit-retry) | Retry that respects provider rate-limit headers (JS) |
| [chat-export-md](https://github.com/mohammed-saray/chat-export-md) | ChatGPT / Claude / Gemini exports → Markdown |
| **mcp-token-audit** | Measure how many tokens each MCP server's tools cost |
| [logslim](https://github.com/mohammed-saray/logslim) | Shrink logs and stack traces before pasting them into a chat |
| [chunkwise](https://github.com/mohammed-saray/chunkwise) | Split big files into token-budgeted chunks with continuation prompts |
| [ai-reset-clock](https://github.com/mohammed-saray/ai-reset-clock) | When does my quota reset? A countdown in your timezone |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)

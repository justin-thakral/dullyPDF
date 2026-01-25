# MCP (DullyPDF)

This folder documents the MCP setup for DullyPDF and hosts the custom MCP server that can call backend endpoints and perform Firebase login.

## Layout

- `mcp/server/`: Custom MCP server code.
- `mcp/.env.local`: Local-only secrets for the MCP server (git-ignored).
- `mcp/allowlist.prod.json`: Minimal prod allowlist skeleton.
- `mcp/devtools.md`: Chrome DevTools live viewing steps.
- `scripts/start-chrome-debug.sh`: Helper for starting a dedicated Chrome instance with a free debug port.
- `scripts/start-chrome-debug.ps1`: Windows helper for starting a dedicated Chrome instance with a free debug port.
- `scripts/start-codex-debug.sh`: Starts Codex attached to the latest Chrome debug session.
- `scripts/start-codex-debug.ps1`: Windows helper to start Codex attached to the latest Chrome debug session.
- `mcp/debugging/`: MCP artifacts (screenshots, logs, traces).

## Quick start (dev)

1. Create `mcp/.env.local` from `mcp/.env.local.example` and fill in values.
2. Install MCP server dependencies:
   ```bash
   cd mcp/server
   npm install
   ```
3. Add a Codex MCP entry in `~/.codex/config.toml` (disabled by default):
   ```toml
   [mcp_servers.dullypdf-dev]
   command = "node"
   args = ["/home/dully/projects/dullyPDF/mcp/server/index.js"]
   cwd = "/home/dully/projects/dullyPDF"
   enabled = false
   ```
4. Enable the MCP server for a session and use it from Codex. The server refuses to start if the working directory is outside this repo.

## OpenAI key (dev)

If you want Map DB or OpenAI rename to work locally, set `OPENAI_API_KEY` in `mcp/.env.local`. `scripts/run-backend-dev.sh` sources it when present.

## Firebase login

The MCP server uses the Firebase email/password REST flow and caches the ID token in memory. Store credentials only in `mcp/.env.local`.

## Allowlist behavior

- Dev defaults to `DULLY_MCP_ALLOWLIST_MODE=auto`, which loads the allowlist from `/openapi.json`.
- Prod defaults to `DULLY_MCP_ALLOWLIST_MODE=file`, which reads `mcp/allowlist.prod.json`.
- If `DULLY_MCP_ENV` is unset, the server infers `prod` when `DULLY_MCP_API_BASE_URL` is not local.

## Tool summary

- `auth.login`, `auth.refresh`, `auth.status`, `auth.logout`
- `api.request`, `api.uploadFile`
- `allowlist.refresh`, `allowlist.list`
- `config.status`

`api.uploadFile` only accepts file paths inside this repo.

## DevTools live viewing

See `mcp/devtools.md` for Chrome DevTools setup so you can watch UI automation and capture screenshots.

## Prod skeleton

Prod is disabled by default. Set `DULLY_MCP_ENV=prod` and keep `DULLY_MCP_ALLOW_WRITE=0` so non-GET calls are blocked unless you explicitly enable them by setting `DULLY_MCP_ALLOW_WRITE=1`. The default prod allowlist lives at `mcp/allowlist.prod.json`.

## Artifacts

Write UI proof to `mcp/debugging/mcp-screenshots`. If you add request/response logging later, keep it under `mcp/debugging/` as well.

## Cleanup

```bash
python3 mcp/cleanOutput.py --logs --screenshots
```

Use `--snapshots`, `--sessions`, or `--all` as needed. Add `--dry-run` to preview. You can also run `python3 clean.py --mcp` from the repo root.

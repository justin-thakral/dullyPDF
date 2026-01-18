# Chrome DevTools (Live UI Proof)

Use this when you want to watch the MCP click/type in the UI and capture screenshots.

## Start Chrome with remote debugging

Close all Chrome windows first (Chrome locks the profile directory). Then start a dedicated instance.

### Windows PowerShell

```powershell
$chrome=@((Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),(Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),(Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'))|?{Test-Path $_}|select -First 1; if(-not $chrome){throw 'chrome.exe not found'}; $profileDir=Join-Path $env:TEMP 'chrome-codex'; New-Item -ItemType Directory -Force $profileDir | Out-Null; $urls=@('http://localhost:5173','http://wsl.localhost:5173'); $url=$urls|?{try{Invoke-WebRequest -UseBasicParsing -Method Head -TimeoutSec 1 $_|Out-Null;$true}catch{$false}}|select -First 1; if(-not $url){$url='about:blank'}; & $chrome --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir="$profileDir" $url
```

### Linux/macOS

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-codex http://localhost:5173
```

## Multiple instances (recommended for parallel terminals)

Run a separate Chrome with a new port and a new profile directory. Do not reuse `--user-data-dir`.

### Detect if a debug instance already exists

If this returns JSON, a debug instance is already running on that port:

```bash
curl http://127.0.0.1:9222/json/version
```

If it exists, start another instance on the next port (e.g. 9223) and use a new profile dir:

```bash
google-chrome --remote-debugging-port=9223 --remote-debugging-address=127.0.0.1 --user-data-dir=/tmp/chrome-codex-9223 http://localhost:5173
```

If you reuse a profile directory, Chrome will refuse to start. A `SingletonLock` file inside that directory is a strong signal that a profile is already in use.

If you want a one-command helper, use:

```bash
scripts/start-chrome-debug.sh
```

```powershell
scripts\start-chrome-debug.ps1
```

## Chrome-first workflow for extra terminals

Use this when you want each Codex terminal to attach to its own Chrome instance without editing configs.

1) Start Chrome (picks a free port and writes the session file):

```bash
scripts/start-chrome-debug.sh
```

```powershell
scripts\start-chrome-debug.ps1
```

2) In a new terminal, attach Codex to the latest Chrome session:

```bash
scripts/start-codex-debug.sh
```

```powershell
scripts\start-codex-debug.ps1
```

To attach to a specific port:

```bash
scripts/start-codex-debug.sh 9224
```

```powershell
scripts\start-codex-debug.ps1 -Port 9224
```

Each run writes a port-specific session file (`mcpDebugging/chrome-debug-session-PORT.env`) and updates `mcpDebugging/chrome-debug-session.env` as the latest session.

## Verify CDP is live

```bash
curl http://127.0.0.1:9222/json/version
```

## WSL port proxy (if needed)

If Codex runs inside WSL and cannot reach Windows Chrome:

```powershell
# Find your WSL gateway IP from inside WSL (often the default route)
#   ip route | grep default
# Example used below: 172.19.240.1
netsh interface portproxy add v4tov4 listenaddress=172.19.240.1 listenport=9222 connectaddress=127.0.0.1 connectport=9222
netsh advfirewall firewall add rule name="Chrome Remote Debugging 9222" dir=in action=allow protocol=TCP localport=9222
```

Then verify from WSL:

```bash
curl http://172.19.240.1:9222/json/version
```

## Notes

- Keep this Chrome window open while MCP is active.
- Use a unique port and profile directory for each parallel MCP session.
- Use `mcpDebugging/mcp-screenshots` for UI proof screenshots.

## Codex MCP config reminder

Ensure `chrome-devtools` is configured in `~/.codex/config.toml` with `--browserUrl http://127.0.0.1:9222` so Codex can attach to the live Chrome instance.

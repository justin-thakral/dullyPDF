#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
session_file="${repo_root}/mcp/debugging/chrome-debug-session.env"
port="${1:-}"

if [ -z "$port" ]; then
  if [ ! -f "$session_file" ]; then
    "${repo_root}/scripts/start-chrome-debug.sh"
  fi
  if [ -f "$session_file" ]; then
    set -a
    . "$session_file"
    set +a
    port="${CHROME_DEBUG_PORT:-}"
  fi
fi

if [ -z "$port" ]; then
  echo "No Chrome debug port available. Run scripts/start-chrome-debug.sh first." >&2
  exit 1
fi

base_config="${CODEX_CONFIG_BASE:-$HOME/.codex/config.toml}"
if [ ! -f "$base_config" ]; then
  echo "Codex config not found: $base_config" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to update the Codex config." >&2
  exit 1
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "codex command not found in PATH." >&2
  exit 1
fi

tmp_config="$(mktemp /tmp/codex-config-XXXX.toml)"
cp "$base_config" "$tmp_config"

python3 - "$tmp_config" "$port" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
port = sys.argv[2]
text = path.read_text()
pattern = re.compile(r'^\[mcp_servers\.chrome-devtools\]\s*$', re.M)
match = pattern.search(text)
if not match:
    sys.stderr.write("chrome-devtools section not found in config\n")
    sys.exit(1)
start = match.end()
next_section = re.search(r'^\[.+\]\s*$', text[start:], re.M)
end = start + next_section.start() if next_section else len(text)
section = text[start:end]
new_url = f"http://127.0.0.1:{port}"
url_pattern = re.compile(r'http://(127\.0\.0\.1|localhost|wsl\.localhost):\d+')
section_updated = url_pattern.sub(new_url, section)
if section_updated == section:
    if re.search(r'^\s*args\s*=', section, re.M):
        sys.stderr.write("chrome-devtools args found without a browserUrl to replace\n")
        sys.exit(1)
    section_updated = section.rstrip() + "\nargs = [\"--browserUrl\", \"" + new_url + "\"]\n"
text = text[:start] + section_updated + text[end:]
path.write_text(text)
PY

trap 'rm -f "$tmp_config"' EXIT

echo "Attaching Codex to http://127.0.0.1:$port"
CODEX_CONFIG="$tmp_config" codex

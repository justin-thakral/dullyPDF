#!/usr/bin/env bash
set -euo pipefail

ports=({9222..9235})
profile_base="${TMPDIR:-/tmp}/chrome-codex"
urls=("http://localhost:5173" "http://wsl.localhost:5173" "about:blank")
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
session_dir="${repo_root}/mcpDebugging"
session_file_latest="${session_dir}/chrome-debug-session.env"

is_port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" | awk 'NR>1 {found=1} END {exit found?0:1}'
    return $?
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | awk '{print $4}' | grep -qE "(^|[.:])$port$"
    return $?
  fi
  return 1
}

port=""
for candidate in "${ports[@]}"; do
  if is_port_in_use "$candidate"; then
    continue
  fi
  port="$candidate"
  break
done

if [ -z "$port" ]; then
  echo "No free debug port found in: ${ports[*]}" >&2
  exit 1
fi

profile_dir="${profile_base}-${port}"
mkdir -p "$profile_dir"
mkdir -p "$session_dir"
session_file_port="${session_dir}/chrome-debug-session-${port}.env"

target="about:blank"
if command -v curl >/dev/null 2>&1; then
  for url in "${urls[@]}"; do
    if curl -fsS -o /dev/null --max-time 1 "$url"; then
      target="$url"
      break
    fi
  done
else
  target="${urls[0]}"
fi

os_name="$(uname -s)"
if [ "$os_name" = "Darwin" ]; then
  open -na "Google Chrome" --args \
    --remote-debugging-port="$port" \
    --remote-debugging-address=127.0.0.1 \
    --user-data-dir="$profile_dir" \
    "$target"
  cat > "$session_file_port" <<EOF
CHROME_DEBUG_PORT=$port
CHROME_DEBUG_URL=http://127.0.0.1:$port
CHROME_DEBUG_PROFILE=$profile_dir
EOF
  cp -f "$session_file_port" "$session_file_latest"
  echo "Chrome debug session: $session_file_port"
  echo "Chrome debug latest: $session_file_latest"
  echo "CHROME_DEBUG_PORT=$port"
  echo "DevTools: http://127.0.0.1:$port/json/version"
  exit 0
fi

chrome_cmd=""
for candidate in google-chrome google-chrome-stable chromium chromium-browser chrome; do
  if command -v "$candidate" >/dev/null 2>&1; then
    chrome_cmd="$candidate"
    break
  fi
done

if [ -z "$chrome_cmd" ]; then
  echo "Chrome binary not found. Install Chrome or Chromium." >&2
  exit 1
fi

"$chrome_cmd" \
  --remote-debugging-port="$port" \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$profile_dir" \
  "$target"

cat > "$session_file_port" <<EOF
CHROME_DEBUG_PORT=$port
CHROME_DEBUG_URL=http://127.0.0.1:$port
CHROME_DEBUG_PROFILE=$profile_dir
EOF
cp -f "$session_file_port" "$session_file_latest"
echo "Chrome debug session: $session_file_port"
echo "Chrome debug latest: $session_file_latest"
echo "CHROME_DEBUG_PORT=$port"
echo "DevTools: http://127.0.0.1:$port/json/version"

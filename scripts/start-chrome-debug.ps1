$ports = 9222..9235
$port = $null
foreach ($p in $ports) {
  $inUse = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  if (-not $inUse) {
    $port = $p
    break
  }
}
if (-not $port) {
  throw "No free debug port found in $($ports -join ', ')."
}

$profileDir = Join-Path $env:TEMP "chrome-codex-$port"
New-Item -ItemType Directory -Force $profileDir | Out-Null
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$sessionDir = Join-Path $repoRoot 'mcpDebugging'
New-Item -ItemType Directory -Force $sessionDir | Out-Null
$sessionFileLatest = Join-Path $sessionDir 'chrome-debug-session.env'
$sessionFilePort = Join-Path $sessionDir "chrome-debug-session-$port.env"

$chrome = @(
  (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
  (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
  (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $chrome) {
  throw 'chrome.exe not found'
}

$urls = @('http://localhost:5173','http://wsl.localhost:5173','about:blank')
$url = $urls | Where-Object {
  try {
    Invoke-WebRequest -UseBasicParsing -Method Head -TimeoutSec 1 $_ | Out-Null
    $true
  } catch {
    $false
  }
} | Select-Object -First 1
if (-not $url) { $url = 'about:blank' }

& $chrome --remote-debugging-port=$port --remote-debugging-address=127.0.0.1 --user-data-dir="$profileDir" $url
$sessionPayload = @(
  "CHROME_DEBUG_PORT=$port",
  "CHROME_DEBUG_URL=http://127.0.0.1:$port",
  "CHROME_DEBUG_PROFILE=$profileDir"
) -join "`n"
$sessionPayload | Set-Content -Path $sessionFilePort -Encoding ASCII
Copy-Item $sessionFilePort $sessionFileLatest -Force
Write-Host "Chrome debug session: $sessionFilePort"
Write-Host "Chrome debug latest: $sessionFileLatest"
Write-Host "CHROME_DEBUG_PORT=$port"
Write-Host "DevTools: http://127.0.0.1:$port/json/version"

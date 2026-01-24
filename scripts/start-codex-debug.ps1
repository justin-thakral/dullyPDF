param(
  [int]$Port
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$sessionFile = Join-Path $repoRoot 'mcp\debugging\chrome-debug-session.env'

if (-not $Port) {
  if (-not (Test-Path $sessionFile)) {
    & (Join-Path $repoRoot 'scripts\start-chrome-debug.ps1')
  }
  if (Test-Path $sessionFile) {
    foreach ($line in Get-Content $sessionFile) {
      if ($line -match '^CHROME_DEBUG_PORT=(\d+)') {
        $Port = [int]$Matches[1]
        break
      }
    }
  }
}

if (-not $Port) {
  throw "No Chrome debug port available. Run scripts\\start-chrome-debug.ps1 first."
}

$baseConfig = if ($env:CODEX_CONFIG_BASE) { $env:CODEX_CONFIG_BASE } else { Join-Path $env:USERPROFILE '.codex\config.toml' }
if (-not (Test-Path $baseConfig)) {
  throw "Codex config not found: $baseConfig"
}

$tempConfig = Join-Path $env:TEMP ("codex-config-" + [guid]::NewGuid().ToString() + ".toml")
Copy-Item $baseConfig $tempConfig

$content = Get-Content $tempConfig -Raw
$sectionMatch = [regex]::Match($content, '(?ms)^\[mcp_servers\.chrome-devtools\]\s*.*?(?=^\[|\z)')
if (-not $sectionMatch.Success) {
  throw "chrome-devtools section not found in config"
}
$newUrl = "http://127.0.0.1:$Port"
$sectionText = $sectionMatch.Value
$updatedSection = [regex]::Replace($sectionText, 'http://(127\.0\.0\.1|localhost|wsl\.localhost):\d+', $newUrl)
if ($updatedSection -eq $sectionText) {
  if ($sectionText -match '(?m)^\s*args\s*=') {
    throw "chrome-devtools args found without a browserUrl to replace"
  }
  $updatedSection = $sectionText.TrimEnd() + "`r`nargs = [\"--browserUrl\", \"$newUrl\"]`r`n"
}
$newContent = $content.Substring(0, $sectionMatch.Index) + $updatedSection + $content.Substring($sectionMatch.Index + $sectionMatch.Length)
Set-Content -Path $tempConfig -Value $newContent -Encoding ASCII

try {
  $env:CODEX_CONFIG = $tempConfig
  Write-Host "Attaching Codex to $newUrl"
  & codex
} finally {
  Remove-Item $tempConfig -ErrorAction SilentlyContinue
}

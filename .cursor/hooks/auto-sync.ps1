# Auto-sync local Aethelgard changes to GitHub after an agent session ends.
# Reads Cursor stop-hook JSON from stdin; always exits 0 (fail-open).

$ErrorActionPreference = "Continue"
try { $null = [Console]::In.ReadToEnd() } catch {}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repoRoot

function Write-HookOk {
  Write-Output "{}"
}

# Only run if this is a git repo with a remote
if (-not (Test-Path (Join-Path $repoRoot ".git"))) {
  Write-HookOk
  exit 0
}

$remote = git remote get-url origin 2>$null
if (-not $remote) {
  Write-HookOk
  exit 0
}

git add -A 2>$null
$status = git status --porcelain 2>$null
if (-not $status) {
  # Still try a push in case local commits are ahead
  git push -u origin HEAD 2>$null | Out-Null
  Write-HookOk
  exit 0
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
$msg = "chore: auto-sync $stamp"
git commit -m $msg 2>$null | Out-Null
git push -u origin HEAD 2>$null | Out-Null

Write-HookOk
exit 0

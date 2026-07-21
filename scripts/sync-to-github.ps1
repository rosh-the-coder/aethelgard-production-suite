# Manual sync: commit all local changes and push to GitHub.
# Usage: .\scripts\sync-to-github.ps1 ["optional commit message"]

param(
  [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if (-not (Test-Path ".git")) {
  Write-Error "Not a git repository: $repoRoot"
}

git add -A
$status = git status --porcelain
if (-not $status) {
  Write-Host "Nothing to commit."
  git push -u origin HEAD
  exit 0
}

if (-not $Message) {
  $Message = "chore: sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

git commit -m $Message
git push -u origin HEAD
Write-Host "Synced to GitHub."

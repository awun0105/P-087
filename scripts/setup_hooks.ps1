# Install git pre-push hook for AI log submission (Windows PowerShell).
# Run once after cloning: powershell -ExecutionPolicy Bypass -File scripts\setup_hooks.ps1

$ErrorActionPreference = 'Stop'

# Build the path without Resolve-Path: the hook does not exist yet on a fresh
# clone, and Resolve-Path throws for missing paths.
$HookDir = Join-Path (Get-Location) '.git/hooks'
if (-not (Test-Path $HookDir)) { New-Item -ItemType Directory -Path $HookDir | Out-Null }
$HookFile = Join-Path $HookDir 'pre-push'

# Git on Windows runs hooks via Git Bash, so the hook body must be bash.
$HookBody = @'
#!/usr/bin/env bash
# Pre-push: sweep recent Antigravity / Gemini prompts, then submit AI logs.
bash scripts/_pyrun.sh scripts/log_antigravity.py --auto || true
bash scripts/_pyrun.sh scripts/submit_log.py || true
exit 0
'@

$HookContent = ($HookBody.Trim() -replace "`r`n", "`n") + "`n"
[System.IO.File]::WriteAllText($HookFile, $HookContent, [System.Text.UTF8Encoding]::new($false))
Write-Host "[ai-log] Git pre-push hook installed."

# Mark it executable for Git Bash (no-op if bash is not on PATH).
try { bash -c "chmod +x '$HookFile'" 2>$null } catch {}

if (-not (Test-Path .ai-log)) { New-Item -ItemType Directory -Path .ai-log | Out-Null }
if (-not (Test-Path .ai-log/.gitkeep)) { New-Item -ItemType File -Path .ai-log/.gitkeep | Out-Null }

Write-Host "[ai-log] Setup complete. Configure AI_LOG_SERVER in your .env file."

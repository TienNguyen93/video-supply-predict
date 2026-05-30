$ErrorActionPreference = 'Stop'
$REPO = 'C:\Users\nguye\Documents\antigravity\serene-hypatia'
$PIP = "$REPO\.venv\Scripts\pip.exe"

Write-Host "Installing missing: pydantic-settings"
& $PIP install "pydantic-settings>=2.2.0"
Write-Host "Done"

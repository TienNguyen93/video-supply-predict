$site = 'C:\Users\nguye\Documents\antigravity\serene-hypatia\.venv\Lib\site-packages'
Write-Host "Site-packages at: $site"
Get-ChildItem $site | Where-Object { $_.Name -match '^(pytest|duckdb|pandas|pydantic|structlog|numpy)' } | Select-Object -ExpandProperty Name

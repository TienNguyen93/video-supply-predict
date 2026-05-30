$python = 'C:\Users\nguye\Documents\antigravity\serene-hypatia\.venv\Scripts\python.exe'
Write-Host "Python: $python"
Write-Host "--- Checking installed packages ---"
& $python -c "import pytest; import duckdb; import pandas; import pydantic; import structlog; print('All core packages present')"
Write-Host "--- Running tests ---"
& $python -m pytest tests/unit -v --tb=short --no-header 2>&1

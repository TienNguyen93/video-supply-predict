$ROOT = 'C:\Users\nguye\Documents\antigravity\serene-hypatia'

$dirs = @(
    'src\ingestion\generators',
    'src\features',
    'src\models',
    'src\agents',
    'src\api\routers',
    'src\dashboard\panels',
    'dbt\models\staging',
    'dbt\models\intermediate',
    'dbt\models\marts',
    'dags',
    'tests\unit',
    'tests\integration',
    'docker',
    'configs',
    'scripts',
    'docs\decisions',
    '.github\workflows'
)

foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ROOT $d) | Out-Null
}

$inits = @(
    'src\__init__.py',
    'src\ingestion\__init__.py',
    'src\ingestion\generators\__init__.py',
    'src\features\__init__.py',
    'src\models\__init__.py',
    'src\agents\__init__.py',
    'src\api\__init__.py',
    'src\api\routers\__init__.py',
    'src\dashboard\__init__.py',
    'src\dashboard\panels\__init__.py',
    'tests\__init__.py',
    'tests\unit\__init__.py',
    'tests\integration\__init__.py'
)

foreach ($f in $inits) {
    $path = Join-Path $ROOT $f
    if (-not (Test-Path $path)) {
        '# init' | Out-File -Encoding utf8 $path
    }
}

Write-Host 'Directory skeleton created successfully'

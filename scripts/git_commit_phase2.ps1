$ErrorActionPreference = 'Stop'
$REPO = 'C:\Users\nguye\Documents\antigravity\serene-hypatia'
Set-Location $REPO
git add -A
git commit -m 'feat: Phase 2 -- synthetic data generators, DuckDB loader, velocity features

- src/ingestion/schemas.py: Pydantic v2 models (SKURecord, VideoRecord, EngagementEvent, VideoSKUBridge)
- src/ingestion/generators/sku_generator.py: 50-SKU catalog generator with 8 categories, viral sensitivity, risk-varied stock levels
- src/ingestion/generators/video_generator.py: 200 videos x 48h timeseries generator with viral growth curves
- src/ingestion/loader.py: DuckDB batch loader with DDL, DataFrame converters, context manager
- src/features/velocity.py: rolling 3h velocity, acceleration, engagement score features
- scripts/seed_historical_data.py: full end-to-end seed (50 SKUs, 200 videos, 9600 events in 1.6s)
- tests/unit/test_schemas.py: 12 Pydantic validation tests
- tests/unit/test_generators.py: 32 generator tests (reproducibility, statistical sanity, rate bounds)
- All 50 unit tests passing'
Write-Host "Committed Phase 2"

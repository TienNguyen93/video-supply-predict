#!/usr/bin/env bash
# ============================================================
# init_db.sh — Initialize local DuckDB data directory
# Run once before first `make seed`
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$REPO_ROOT/data"
DB_PATH="$DATA_DIR/warehouse.duckdb"

echo "→ Creating data directory at $DATA_DIR"
mkdir -p "$DATA_DIR"

if [ -f "$DB_PATH" ]; then
  echo "⚠  DuckDB file already exists at $DB_PATH"
  echo "   Delete it manually if you want a fresh database."
  exit 0
fi

echo "→ Initialising empty DuckDB warehouse..."
python -c "
import duckdb
con = duckdb.connect('$DB_PATH')
con.execute('CREATE SCHEMA IF NOT EXISTS raw;')
con.execute('CREATE SCHEMA IF NOT EXISTS staging;')
con.execute('CREATE SCHEMA IF NOT EXISTS intermediate;')
con.execute('CREATE SCHEMA IF NOT EXISTS marts;')
con.close()
print('✓ Schemas created: raw, staging, intermediate, marts')
"

echo "✓ Database initialised at $DB_PATH"

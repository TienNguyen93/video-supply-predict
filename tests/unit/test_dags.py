from __future__ import annotations

import signal
import sys
from unittest.mock import MagicMock

# Mock POSIX-only items before importing airflow on Windows
try:
    import fcntl  # noqa: F401
except ImportError:
    sys.modules["fcntl"] = MagicMock()

if not hasattr(signal, "SIGALRM"):
    signal.SIGALRM = 14
if not hasattr(signal, "setitimer"):
    signal.setitimer = lambda *args, **kwargs: None
if not hasattr(signal, "ITIMER_REAL"):
    signal.ITIMER_REAL = 0

import pytest
from airflow.models import DagBag


@pytest.mark.unit
def test_dag_bag_import_errors():
    """Verify that all Airflow DAGs can be parsed and have no import errors."""
    dagbag = DagBag(dag_folder="dags", include_examples=False)
    assert len(dagbag.import_errors) == 0, f"DAG import errors: {dagbag.import_errors}"

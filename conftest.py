"""Pytest configuration: make the repository root importable so tests can
`from reference.octet_ref import ...` regardless of how pytest is invoked
(bare `pytest` vs `python -m pytest`)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

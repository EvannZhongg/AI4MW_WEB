from __future__ import annotations

import sys
from pathlib import Path


LOCAL_DEPS = Path(__file__).resolve().parent / ".deps"
if LOCAL_DEPS.exists():
    deps_path = str(LOCAL_DEPS)
    if deps_path not in sys.path:
        sys.path.insert(0, deps_path)

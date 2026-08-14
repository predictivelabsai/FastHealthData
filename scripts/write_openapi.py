#!/usr/bin/env python3
"""Write the deterministic FastHealthData OpenAPI snapshot."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.api import api  # noqa: E402


(ROOT / "swagger.json").write_text(
    json.dumps(api.openapi(), indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("Wrote swagger.json")

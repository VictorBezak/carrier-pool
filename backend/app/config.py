from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def data_dir() -> Path:
    """Where the TMS sync files live.

    Overridable so the container can mount them somewhere else and so tests can
    point at a fixture directory.
    """
    return Path(os.environ.get("CARRIER_POOL_DATA_DIR", _DEFAULT_DATA_DIR))


def cors_origins() -> list[str]:
    raw = os.environ.get("CARRIER_POOL_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]

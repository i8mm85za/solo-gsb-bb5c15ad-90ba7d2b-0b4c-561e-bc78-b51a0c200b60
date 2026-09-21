"""Runtime configuration (environment driven)."""
from __future__ import annotations

import os

#: Hard server-side cap for the expansion; requests may ask for less.
MAX_EXPAND_STEPS = int(os.getenv("MAX_EXPAND_STEPS", "1000"))

#: TCP port the container listens on (informational; uvicorn binds it).
PORT = int(os.getenv("PORT", "8000"))

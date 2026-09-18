"""Local trading journal. Data stays on this machine; nothing is uploaded."""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load repo `.env` into os.environ. Existing process env wins."""
    here = Path(__file__).resolve().parent
    for path in (here.parent / ".env", here / ".env"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
        break


_load_dotenv()

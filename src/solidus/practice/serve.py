"""本机练习页进程。只监听 127.0.0.1。"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import uvicorn

from solidus.practice.loader import load_practice_app


def main() -> None:
    raw = os.environ.get("PRACTICE_BASE_URL", "http://127.0.0.1:8765")
    parsed = urlparse(raw)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    uvicorn.run(load_practice_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

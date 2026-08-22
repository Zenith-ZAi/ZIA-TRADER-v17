"""Launcher do backend em thread separada para uso local supervisionado."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn

from config.settings import settings
from main import app


class BackgroundAPIRuntime:
    def __init__(self, host: str = "127.0.0.1", port: int | None = None):
        self.host = host
        self.port = int(port or settings.API_PORT)
        self.server = uvicorn.Server(uvicorn.Config(app, host=self.host, port=self.port, log_level="info"))
        self.thread: threading.Thread | None = None

    def start(self) -> threading.Thread:
        if self.thread and self.thread.is_alive():
            return self.thread
        self.thread = threading.Thread(target=self.server.run, name="zia-fastapi", daemon=True)
        self.thread.start()
        return self.thread

    def stop(self) -> None:
        self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa FastAPI ZIA em thread de background")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=settings.API_PORT)
    args = parser.parse_args()
    runtime = BackgroundAPIRuntime(args.host, args.port)
    runtime.start()
    signal.signal(signal.SIGINT, lambda *_: runtime.stop())
    signal.signal(signal.SIGTERM, lambda *_: runtime.stop())
    try:
        while runtime.thread and runtime.thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        runtime.stop()


if __name__ == "__main__":
    main()

from __future__ import annotations

import logging
import sys
from collections import deque
from pathlib import Path


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 200) -> None:
        super().__init__()
        self.buffer: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buffer.append(self.format(record))
        except Exception:  # noqa: BLE001 — logging must never raise
            self.handleError(record)

    def lines(self) -> list[str]:
        return list(self.buffer)


_ring = RingBufferHandler(capacity=300)


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> RingBufferHandler:
    root = logging.getLogger()
    if getattr(root, "_tiny_station_configured", False):
        return _ring

    root.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    _ring.setFormatter(formatter)
    root.addHandler(_ring)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "station.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    root._tiny_station_configured = True  # type: ignore[attr-defined]
    return _ring


def get_ring() -> RingBufferHandler:
    return _ring

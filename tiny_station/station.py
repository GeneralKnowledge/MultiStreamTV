from __future__ import annotations

from tiny_station.broadcast.engine import BroadcastEngine
from tiny_station.config import StationConfig, load_config


class Station:
    """Application root — wires config, broadcast engine, and shared state."""

    def __init__(self, config: StationConfig | None = None) -> None:
        self.config = config or load_config()
        self.broadcast = BroadcastEngine(self.config)

    @classmethod
    def from_path(cls, path: str | None = None) -> "Station":
        return cls(load_config(path))

    def start(self, background: bool = True) -> None:
        self.broadcast.start(background=background)

    def stop(self) -> None:
        self.broadcast.stop()

    def status(self) -> dict:
        data = self.broadcast.status_dict()
        data["station_name"] = self.config.station_name
        data["media_count"] = len(self.broadcast.library.scan())
        return data

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent.parent


class StreamSettings(BaseModel):
    url: str = ""
    key: str = ""
    # When url is empty, write a local preview file instead.
    local_output: str = "data/preview/broadcast.ts"
    width: int = 1280
    height: int = 720
    fps: int = 30
    video_bitrate: str = "2000k"
    audio_bitrate: str = "128k"
    audio_rate: int = 44100
    preset: str = "ultrafast"
    gop: int = 60

    def rtmp_destination(self) -> str | None:
        url = (self.url or os.environ.get("STREAM_URL", "")).rstrip("/")
        key = self.key or os.environ.get("STREAM_KEY", "")
        if not url:
            return None
        if key:
            return f"{url}/{key}"
        return url


class OverlaySettings(BaseModel):
    logo: bool = True
    now_playing: bool = True
    clock: bool = True
    live_badge: bool = True
    logo_path: str = ""


class ProgrammeWeights(BaseModel):
    music: float = 0.70
    video: float = 0.10
    ident: float = 0.08
    announcement: float = 0.07
    jingle: float = 0.05


class ProgrammeDef(BaseModel):
    name: str
    duration_minutes: int = 60
    mode: str = "weighted"  # weighted | structure
    weights: ProgrammeWeights = Field(default_factory=ProgrammeWeights)
    structure: list[str] = Field(default_factory=list)
    visual_preference: list[str] = Field(
        default_factory=lambda: ["visual", "image", "generated"]
    )


class ScheduleSlot(BaseModel):
    programme: str


class StationConfig(BaseModel):
    station_name: str = "Tiny Station"
    media_root: str = "media"
    data_dir: str = "data"
    rescan_seconds: int = 30
    fallback_programme: str = "autonomous"
    stream: StreamSettings = Field(default_factory=StreamSettings)
    overlays: OverlaySettings = Field(default_factory=OverlaySettings)
    programmes: dict[str, ProgrammeDef] = Field(default_factory=dict)
    schedule: dict[str, ScheduleSlot] = Field(default_factory=dict)
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    @property
    def media_path(self) -> Path:
        path = Path(self.media_root)
        return path if path.is_absolute() else ROOT / path

    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir)
        return path if path.is_absolute() else ROOT / path


def default_programmes() -> dict[str, ProgrammeDef]:
    return {
        "autonomous": ProgrammeDef(
            name="Autonomous",
            duration_minutes=60,
            mode="weighted",
            weights=ProgrammeWeights(),
        ),
        "late-night": ProgrammeDef(
            name="Late Night",
            duration_minutes=90,
            mode="structure",
            structure=[
                "ident",
                "music",
                "music",
                "announcement",
                "music",
                "video",
                "music",
                "ident",
                "music",
            ],
            visual_preference=["visual", "image"],
        ),
        "strange-sunday": ProgrammeDef(
            name="Strange Sunday",
            duration_minutes=120,
            mode="weighted",
            weights=ProgrammeWeights(
                music=0.45, video=0.30, ident=0.10, announcement=0.10, jingle=0.05
            ),
            visual_preference=["visual", "video", "image"],
        ),
    }


def load_config(path: str | Path | None = None) -> StationConfig:
    config_path = Path(path) if path else ROOT / "config" / "station.yaml"
    data: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"Config must be a mapping: {config_path}")
            data = loaded

    cfg = StationConfig.model_validate(data)
    if not cfg.programmes:
        cfg.programmes = default_programmes()
    if "autonomous" not in cfg.programmes:
        cfg.programmes["autonomous"] = default_programmes()["autonomous"]

    # Env overrides for stream
    if os.environ.get("STREAM_URL"):
        cfg.stream.url = os.environ["STREAM_URL"]
    if os.environ.get("STREAM_KEY"):
        cfg.stream.key = os.environ["STREAM_KEY"]
    if os.environ.get("STATION_NAME"):
        cfg.station_name = os.environ["STATION_NAME"]

    cfg.data_path.mkdir(parents=True, exist_ok=True)
    (cfg.data_path / "preview").mkdir(parents=True, exist_ok=True)
    (cfg.data_path / "logs").mkdir(parents=True, exist_ok=True)
    return cfg

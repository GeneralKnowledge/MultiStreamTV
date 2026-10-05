from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AssetCategory(str, Enum):
    MUSIC = "music"
    VIDEO = "video"
    VISUAL = "visual"
    IMAGE = "image"
    JINGLE = "jingle"
    IDENT = "ident"
    ANNOUNCEMENT = "announcement"
    VOICE = "voice"
    BACKGROUND = "background"
    OVERLAY = "overlay"
    UNKNOWN = "unknown"


class VisualMode(str, Enum):
    VIDEO = "video"
    LOOPING_VIDEO = "looping_video"
    STATIC_IMAGE = "static_image"
    SLIDESHOW = "slideshow"
    GENERATED = "generated"
    NATIVE = "native"  # use embedded A/V from a video file


class BroadcastStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    BROADCASTING = "broadcasting"
    RECOVERING = "recovering"
    FALLBACK = "fallback"
    ERROR = "error"


@dataclass(slots=True)
class MediaAsset:
    id: str
    path: str
    category: AssetCategory
    media_type: str  # audio | video | image
    duration: float | None = None
    title: str = ""
    artist: str = ""
    tags: list[str] = field(default_factory=list)
    weight: float = 1.0
    has_audio: bool = False
    has_video: bool = False
    width: int | None = None
    height: int | None = None
    codec_video: str | None = None
    codec_audio: str | None = None
    ok: bool = True
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "category": self.category.value,
            "media_type": self.media_type,
            "duration": self.duration,
            "title": self.title,
            "artist": self.artist,
            "tags": list(self.tags),
            "weight": self.weight,
            "has_audio": self.has_audio,
            "has_video": self.has_video,
            "ok": self.ok,
            "notes": self.notes,
        }


@dataclass(slots=True)
class BroadcastSegment:
    """One composable unit of broadcast time."""

    kind: str  # music, video, ident, announcement, fallback, ...
    title: str
    programme: str
    audio: MediaAsset | None = None
    video: MediaAsset | None = None
    overlay: MediaAsset | None = None
    visual_mode: VisualMode = VisualMode.LOOPING_VIDEO
    duration: float | None = None
    now_playing_text: str = ""
    is_fallback: bool = False

    def label(self) -> str:
        return self.now_playing_text or self.title


@dataclass(slots=True)
class StationState:
    status: BroadcastStatus = BroadcastStatus.STOPPED
    programme: str = ""
    now: str = ""
    next: str = ""
    now_kind: str = ""
    next_kind: str = ""
    started_at: float | None = None
    segment_started_at: float | None = None
    segments_played: int = 0
    failures: int = 0
    last_error: str = ""
    stream_target: str = ""
    stream_healthy: bool = False
    encoder_pid: int | None = None
    recent_log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        uptime = 0.0
        if self.started_at is not None:
            import time

            uptime = max(0.0, time.time() - self.started_at)
        return {
            "status": self.status.value,
            "programme": self.programme,
            "now": self.now,
            "next": self.next,
            "now_kind": self.now_kind,
            "next_kind": self.next_kind,
            "uptime_seconds": uptime,
            "segments_played": self.segments_played,
            "failures": self.failures,
            "last_error": self.last_error,
            "stream_target": self.stream_target,
            "stream_healthy": self.stream_healthy,
            "encoder_pid": self.encoder_pid,
            "recent_log": list(self.recent_log[-40:]),
        }

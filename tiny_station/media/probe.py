from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe are required on PATH")


def probe(path: Path) -> dict[str, Any]:
    """Return ffprobe JSON for a media file, or {} on failure."""
    ensure_ffmpeg()
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("ffprobe failed for %s: %s", path, exc)
        return {}

    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def summarize_probe(info: dict[str, Any]) -> dict[str, Any]:
    streams = info.get("streams") or []
    fmt = info.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = None
    for candidate in (fmt.get("duration"), (audio or {}).get("duration"), (video or {}).get("duration")):
        if candidate is not None:
            try:
                duration = float(candidate)
                break
            except (TypeError, ValueError):
                pass

    # Images often report duration 0 or N/A — treat as still
    is_image = False
    if video and video.get("codec_name") in {"png", "mjpeg", "webp", "bmp", "gif"}:
        nb = video.get("nb_frames")
        if nb in (None, "1", 1) or duration in (None, 0, 0.0):
            is_image = True

    return {
        "duration": duration,
        "has_audio": audio is not None,
        "has_video": video is not None and not is_image,
        "is_image": is_image or (video is None and audio is None and Path(fmt.get("filename", "")).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}),
        "width": int(video["width"]) if video and video.get("width") else None,
        "height": int(video["height"]) if video and video.get("height") else None,
        "codec_video": video.get("codec_name") if video else None,
        "codec_audio": audio.get("codec_name") if audio else None,
        "title": (fmt.get("tags") or {}).get("title") or "",
        "artist": (fmt.get("tags") or {}).get("artist") or "",
    }

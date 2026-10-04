from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path

from tiny_station.media.probe import probe, summarize_probe
from tiny_station.models import AssetCategory, MediaAsset

log = logging.getLogger(__name__)

AUDIO_EXT = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus"}
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

DIR_CATEGORY = {
    "music": AssetCategory.MUSIC,
    "video": AssetCategory.VIDEO,
    "videos": AssetCategory.VIDEO,
    "visuals": AssetCategory.VISUAL,
    "visual": AssetCategory.VISUAL,
    "images": AssetCategory.IMAGE,
    "image": AssetCategory.IMAGE,
    "jingles": AssetCategory.JINGLE,
    "jingle": AssetCategory.JINGLE,
    "idents": AssetCategory.IDENT,
    "ident": AssetCategory.IDENT,
    "announcements": AssetCategory.ANNOUNCEMENT,
    "announcement": AssetCategory.ANNOUNCEMENT,
    "voice": AssetCategory.VOICE,
    "voices": AssetCategory.VOICE,
    "background": AssetCategory.BACKGROUND,
    "backgrounds": AssetCategory.BACKGROUND,
    "overlays": AssetCategory.OVERLAY,
    "overlay": AssetCategory.OVERLAY,
}


class MediaLibrary:
    """Filesystem-first media index with automatic discovery."""

    def __init__(self, media_root: Path, rescan_seconds: int = 30) -> None:
        self.media_root = media_root
        self.rescan_seconds = rescan_seconds
        self._assets: dict[str, MediaAsset] = {}
        self._mtime_index: dict[str, float] = {}
        self._lock = threading.RLock()
        self._last_scan = 0.0
        self.media_root.mkdir(parents=True, exist_ok=True)
        for name in DIR_CATEGORY:
            (self.media_root / name).mkdir(parents=True, exist_ok=True)
        (self.media_root / "_fallback").mkdir(parents=True, exist_ok=True)

    def scan(self, force: bool = False) -> list[MediaAsset]:
        now = time.time()
        with self._lock:
            if not force and (now - self._last_scan) < self.rescan_seconds and self._assets:
                return list(self._assets.values())

            seen: set[str] = set()
            for path in sorted(self.media_root.rglob("*")):
                if not path.is_file():
                    continue
                if path.name.startswith("."):
                    continue
                if path.suffix.lower() not in AUDIO_EXT | VIDEO_EXT | IMAGE_EXT:
                    continue
                # Skip nested junk but allow _fallback
                rel = path.relative_to(self.media_root)
                asset_id = self._id_for(rel)
                seen.add(asset_id)
                mtime = path.stat().st_mtime
                if asset_id in self._assets and self._mtime_index.get(asset_id) == mtime:
                    continue
                asset = self._index_file(path, rel)
                self._assets[asset_id] = asset
                self._mtime_index[asset_id] = mtime
                log.info("Indexed: %s (%s, %.1fs)", rel, asset.category.value, asset.duration or 0)

            for stale in [aid for aid in self._assets if aid not in seen]:
                log.info("Removed missing media: %s", self._assets[stale].path)
                del self._assets[stale]
                self._mtime_index.pop(stale, None)

            self._last_scan = now
            return list(self._assets.values())

    def _id_for(self, rel: Path) -> str:
        return hashlib.sha1(str(rel).encode("utf-8")).hexdigest()[:12]

    def _category_for(self, rel: Path) -> AssetCategory:
        parts = [p.lower() for p in rel.parts]
        if parts and parts[0] == "_fallback":
            suffix = rel.suffix.lower()
            if suffix in IMAGE_EXT:
                return AssetCategory.IMAGE
            if suffix in VIDEO_EXT:
                return AssetCategory.VISUAL
            if suffix in AUDIO_EXT:
                return AssetCategory.MUSIC
            return AssetCategory.UNKNOWN
        for part in parts:
            if part in DIR_CATEGORY:
                return DIR_CATEGORY[part]
        # Filename hints
        name = rel.stem.lower()
        for key, cat in (
            ("ident", AssetCategory.IDENT),
            ("jingle", AssetCategory.JINGLE),
            ("announce", AssetCategory.ANNOUNCEMENT),
            ("voice", AssetCategory.VOICE),
            ("logo", AssetCategory.OVERLAY),
        ):
            if key in name:
                return cat
        suffix = rel.suffix.lower()
        if suffix in AUDIO_EXT:
            return AssetCategory.MUSIC
        if suffix in VIDEO_EXT:
            return AssetCategory.VIDEO
        if suffix in IMAGE_EXT:
            return AssetCategory.IMAGE
        return AssetCategory.UNKNOWN

    def _index_file(self, path: Path, rel: Path) -> MediaAsset:
        category = self._category_for(rel)
        suffix = path.suffix.lower()
        info = summarize_probe(probe(path))

        if suffix in IMAGE_EXT or info.get("is_image"):
            media_type = "image"
            has_video = False
            has_audio = False
        elif suffix in VIDEO_EXT or info.get("has_video"):
            media_type = "video"
            has_video = True
            has_audio = bool(info.get("has_audio"))
        else:
            media_type = "audio"
            has_video = False
            has_audio = True

        title = info.get("title") or rel.stem.replace("_", " ").replace("-", " ").strip()
        notes = ""
        ok = True
        if media_type == "video" and not info.get("codec_video"):
            ok = False
            notes = "no video stream"
        if media_type == "audio" and not info.get("has_audio") and not info.get("codec_audio"):
            # still may be ok if probe failed partially
            notes = "probe incomplete"

        return MediaAsset(
            id=self._id_for(rel),
            path=str(path.resolve()),
            category=category,
            media_type=media_type,
            duration=info.get("duration"),
            title=title,
            artist=info.get("artist") or "",
            tags=[category.value, media_type],
            has_audio=has_audio if media_type != "image" else False,
            has_video=has_video,
            width=info.get("width"),
            height=info.get("height"),
            codec_video=info.get("codec_video"),
            codec_audio=info.get("codec_audio"),
            ok=ok,
            notes=notes,
        )

    def all(self) -> list[MediaAsset]:
        with self._lock:
            return list(self._assets.values())

    def by_category(self, *categories: AssetCategory, include_fallback: bool = False) -> list[MediaAsset]:
        wanted = set(categories)
        out: list[MediaAsset] = []
        for asset in self.scan():
            rel = Path(asset.path)
            try:
                in_fallback = "_fallback" in rel.parts
            except Exception:  # noqa: BLE001
                in_fallback = False
            if in_fallback and not include_fallback:
                continue
            if asset.category in wanted and asset.ok:
                out.append(asset)
        return out

    def logos(self) -> list[MediaAsset]:
        images = self.by_category(AssetCategory.IMAGE, AssetCategory.OVERLAY)
        preferred = [a for a in images if "logo" in Path(a.path).stem.lower()]
        return preferred or images

    def visuals(self) -> list[MediaAsset]:
        return self.by_category(AssetCategory.VISUAL, AssetCategory.BACKGROUND) or [
            a for a in self.by_category(AssetCategory.VIDEO) if a.has_video
        ]

    def images(self) -> list[MediaAsset]:
        return [a for a in self.by_category(AssetCategory.IMAGE) if "logo" not in Path(a.path).stem.lower()]

    def fallback_visual(self) -> MediaAsset | None:
        root = self.media_root / "_fallback"
        for name in ("standby.mp4", "fallback.mp4", "standby.png", "fallback.png"):
            path = root / name
            if path.exists():
                rel = path.relative_to(self.media_root)
                return self._index_file(path, rel)
        visuals = self.visuals() or self.images()
        return visuals[0] if visuals else None

    def fallback_audio(self) -> MediaAsset | None:
        root = self.media_root / "_fallback"
        for name in ("silence_tone.mp3", "fallback.mp3", "silence.mp3"):
            path = root / name
            if path.exists():
                rel = path.relative_to(self.media_root)
                return self._index_file(path, rel)
        music = self.by_category(AssetCategory.MUSIC)
        return music[0] if music else None

    def validate(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for asset in self.scan(force=True):
            mark = "✓" if asset.ok else "⚠"
            detail = asset.notes or f"{asset.media_type}"
            if asset.codec_video:
                detail += f" video={asset.codec_video}"
            if asset.codec_audio:
                detail += f" audio={asset.codec_audio}"
            if asset.duration:
                detail += f" {asset.duration:.1f}s"
            rows.append(
                {
                    "mark": mark,
                    "path": str(Path(asset.path).relative_to(self.media_root)),
                    "detail": detail.strip(),
                }
            )
        return rows

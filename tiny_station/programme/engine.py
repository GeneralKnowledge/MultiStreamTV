from __future__ import annotations

import logging
import random
from collections import deque
from datetime import datetime
from typing import Deque

from tiny_station.config import ProgrammeDef, StationConfig
from tiny_station.media.indexer import MediaLibrary
from tiny_station.models import AssetCategory, BroadcastSegment, MediaAsset, VisualMode

log = logging.getLogger(__name__)

KIND_TO_CATEGORY = {
    "music": AssetCategory.MUSIC,
    "video": AssetCategory.VIDEO,
    "visual": AssetCategory.VISUAL,
    "jingle": AssetCategory.JINGLE,
    "ident": AssetCategory.IDENT,
    "announcement": AssetCategory.ANNOUNCEMENT,
    "voice": AssetCategory.VOICE,
}


class ProgrammeEngine:
    """Turns media + programme rules into an endless segment queue."""

    def __init__(
        self,
        library: MediaLibrary,
        config: StationConfig,
        rng: random.Random | None = None,
    ) -> None:
        self.library = library
        self.config = config
        self.rng = rng or random.Random()
        self._structure_index = 0
        self._recent: Deque[str] = deque(maxlen=24)
        self._lookahead: Deque[BroadcastSegment] = deque()

    def current_programme_id(self, when: datetime | None = None) -> str:
        when = when or datetime.now()
        if not self.config.schedule:
            return self.config.fallback_programme

        # schedule keys like "22:00"
        slots = sorted(self.config.schedule.items(), key=lambda kv: kv[0])
        chosen = self.config.fallback_programme
        hhmm = when.strftime("%H:%M")
        for stamp, slot in slots:
            if hhmm >= stamp:
                chosen = slot.programme
        # Before first slot of the day, use last slot
        if hhmm < slots[0][0]:
            chosen = slots[-1][1].programme
        if chosen not in self.config.programmes:
            return self.config.fallback_programme
        return chosen

    def programme_def(self, programme_id: str | None = None) -> ProgrammeDef:
        pid = programme_id or self.current_programme_id()
        return self.config.programmes.get(pid) or self.config.programmes["autonomous"]

    def peek_next(self) -> BroadcastSegment | None:
        self._ensure_lookahead(1)
        return self._lookahead[0] if self._lookahead else None

    def next_segment(self) -> BroadcastSegment:
        self._ensure_lookahead(2)
        if not self._lookahead:
            return self._fallback_segment("empty queue")
        segment = self._lookahead.popleft()
        self._ensure_lookahead(2)
        return segment

    def _ensure_lookahead(self, n: int) -> None:
        while len(self._lookahead) < n:
            self._lookahead.append(self._generate_one())

    def _generate_one(self) -> BroadcastSegment:
        self.library.scan()
        pid = self.current_programme_id()
        prog = self.programme_def(pid)

        if prog.mode == "structure" and prog.structure:
            kind = prog.structure[self._structure_index % len(prog.structure)]
            self._structure_index += 1
        else:
            kind = self._weighted_kind(prog)

        try:
            segment = self._build_segment(kind, prog)
        except Exception as exc:  # noqa: BLE001 — never fail the broadcast
            log.warning("Segment build failed (%s): %s", kind, exc)
            segment = self._fallback_segment(str(exc))

        self._recent.append(segment.audio.path if segment.audio else segment.title)
        return segment

    def _weighted_kind(self, prog: ProgrammeDef) -> str:
        weights = prog.weights.model_dump()
        # Drop kinds with no media so we don't thrash into fallbacks
        available: list[tuple[str, float]] = []
        for kind, weight in weights.items():
            if weight <= 0:
                continue
            if self._candidates_for_kind(kind):
                available.append((kind, weight))
        if not available:
            # Prefer music, else video, else anything
            if self._candidates_for_kind("music"):
                return "music"
            if self._candidates_for_kind("video"):
                return "video"
            return "music"
        kinds, vals = zip(*available)
        return self.rng.choices(list(kinds), weights=list(vals), k=1)[0]

    def _candidates_for_kind(self, kind: str) -> list[MediaAsset]:
        if kind == "ident":
            items = self.library.by_category(AssetCategory.IDENT, AssetCategory.JINGLE)
        elif kind == "jingle":
            items = self.library.by_category(AssetCategory.JINGLE, AssetCategory.IDENT)
        elif kind == "announcement":
            items = self.library.by_category(
                AssetCategory.ANNOUNCEMENT, AssetCategory.VOICE
            )
        elif kind == "video":
            items = [
                a
                for a in self.library.by_category(AssetCategory.VIDEO)
                if a.has_video
            ]
        elif kind == "visual":
            items = self.library.visuals()
        else:
            cat = KIND_TO_CATEGORY.get(kind, AssetCategory.MUSIC)
            items = self.library.by_category(cat)
        # Avoid immediate repeats when possible
        fresh = [a for a in items if a.path not in self._recent]
        return fresh or items

    def _pick(self, items: list[MediaAsset]) -> MediaAsset | None:
        if not items:
            return None
        weights = [max(0.01, a.weight) for a in items]
        return self.rng.choices(items, weights=weights, k=1)[0]

    def _pick_visual(self, prog: ProgrammeDef) -> tuple[MediaAsset | None, VisualMode]:
        for pref in prog.visual_preference:
            if pref == "visual":
                asset = self._pick(self.library.visuals())
                if asset:
                    return asset, VisualMode.LOOPING_VIDEO
            if pref == "image":
                asset = self._pick(self.library.images() or self.library.by_category(AssetCategory.IMAGE))
                if asset:
                    return asset, VisualMode.STATIC_IMAGE
            if pref == "video":
                asset = self._pick(
                    [a for a in self.library.by_category(AssetCategory.VIDEO) if a.has_video]
                )
                if asset:
                    return asset, VisualMode.LOOPING_VIDEO
            if pref == "generated":
                return None, VisualMode.GENERATED
        # Absolute fallback: generated color field
        return None, VisualMode.GENERATED

    def _build_segment(self, kind: str, prog: ProgrammeDef) -> BroadcastSegment:
        overlay = self._pick(self.library.logos()) if self.config.overlays.logo else None

        if kind == "video":
            video = self._pick(self._candidates_for_kind("video"))
            if not video:
                return self._build_segment("music", prog)
            return BroadcastSegment(
                kind="video",
                title=video.title,
                programme=prog.name,
                audio=video if video.has_audio else self._pick(self._candidates_for_kind("music")),
                video=video,
                overlay=overlay,
                visual_mode=VisualMode.NATIVE if video.has_audio else VisualMode.LOOPING_VIDEO,
                duration=video.duration,
                now_playing_text=video.title,
            )

        audio = self._pick(self._candidates_for_kind(kind))
        if not audio:
            # degrade gracefully
            audio = self._pick(self._candidates_for_kind("music"))
            kind = "music" if audio else kind
        if not audio:
            return self._fallback_segment("no audio assets")

        visual, mode = self._pick_visual(prog)
        return BroadcastSegment(
            kind=kind,
            title=audio.title,
            programme=prog.name,
            audio=audio,
            video=visual,
            overlay=overlay,
            visual_mode=mode,
            duration=audio.duration,
            now_playing_text=audio.title,
        )

    def _fallback_segment(self, reason: str) -> BroadcastSegment:
        log.warning("Fallback visual activated (%s)", reason)
        visual = self.library.fallback_visual()
        audio = self.library.fallback_audio()
        mode = VisualMode.LOOPING_VIDEO
        if visual and visual.media_type == "image":
            mode = VisualMode.STATIC_IMAGE
        if visual is None:
            mode = VisualMode.GENERATED
        return BroadcastSegment(
            kind="fallback",
            title="Stand By",
            programme="Fallback",
            audio=audio,
            video=visual,
            overlay=self._pick(self.library.logos()),
            visual_mode=mode,
            duration=10.0,
            now_playing_text="Stand By",
            is_fallback=True,
        )

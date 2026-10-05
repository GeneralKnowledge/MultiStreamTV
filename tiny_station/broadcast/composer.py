from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path

from tiny_station.config import StreamSettings
from tiny_station.models import BroadcastSegment, VisualMode

log = logging.getLogger(__name__)


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )


class SegmentComposer:
    """Compose one broadcast segment to normalized MPEG-TS on stdout."""

    def __init__(self, stream: StreamSettings, station_name: str = "Tiny Station") -> None:
        self.stream = stream
        self.station_name = station_name

    def build_command(self, segment: BroadcastSegment) -> list[str]:
        s = self.stream
        w, h, fps = s.width, s.height, s.fps
        duration = segment.duration or 8.0
        if duration <= 0:
            duration = 8.0
        # Cap runaway durations for safety on tiny VPS demos
        duration = min(duration, 60 * 30)

        cmd: list[str] = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]

        audio_path = segment.audio.path if segment.audio else None
        video_path = segment.video.path if segment.video else None
        overlay_path = segment.overlay.path if segment.overlay else None

        # Inputs
        audio_idx = None
        video_idx = None
        overlay_idx = None
        generated = False
        input_i = 0

        if segment.visual_mode == VisualMode.NATIVE and video_path:
            cmd += ["-i", video_path]
            video_idx = input_i
            audio_idx = input_i if segment.audio and segment.audio.path == video_path else None
            input_i += 1
            if audio_idx is None and audio_path:
                cmd += ["-i", audio_path]
                audio_idx = input_i
                input_i += 1
        else:
            if audio_path:
                cmd += ["-i", audio_path]
                audio_idx = input_i
                input_i += 1

            if segment.visual_mode == VisualMode.STATIC_IMAGE and video_path:
                cmd += ["-loop", "1", "-t", f"{duration:.3f}", "-i", video_path]
                video_idx = input_i
                input_i += 1
            elif segment.visual_mode in {VisualMode.LOOPING_VIDEO, VisualMode.VIDEO} and video_path:
                cmd += ["-stream_loop", "-1", "-t", f"{duration:.3f}", "-i", video_path]
                video_idx = input_i
                input_i += 1
            else:
                # Generated visual — slow color pulse, no GPU
                cmd += [
                    "-f",
                    "lavfi",
                    "-t",
                    f"{duration:.3f}",
                    "-i",
                    f"color=c=0x101820:s={w}x{h}:r={fps}",
                ]
                video_idx = input_i
                input_i += 1
                generated = True

            if audio_idx is None:
                cmd += [
                    "-f",
                    "lavfi",
                    "-t",
                    f"{duration:.3f}",
                    "-i",
                    "anullsrc=channel_layout=stereo:sample_rate=44100",
                ]
                audio_idx = input_i
                input_i += 1

        if overlay_path and Path(overlay_path).exists():
            cmd += ["-i", overlay_path]
            overlay_idx = input_i
            input_i += 1

        # Filter graph
        filters: list[str] = []
        assert video_idx is not None
        assert audio_idx is not None

        if generated:
            filters.append(
                f"[{video_idx}:v]scale={w}:{h},format=yuv420p,"
                f"drawtext=text='{_escape_drawtext(self.station_name)}':fontsize=48:"
                f"fontcolor=white@0.85:x=(w-text_w)/2:y=(h-text_h)/2,"
                f"fps={fps}[base]"
            )
        else:
            filters.append(
                f"[{video_idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p,fps={fps}[base]"
            )

        vlabel = "base"
        if overlay_idx is not None:
            filters.append(
                f"[{overlay_idx}:v]scale=160:-1,format=rgba,colorchannelmixer=aa=0.90[logo]"
            )
            filters.append(f"[{vlabel}][logo]overlay=24:24[v1]")
            vlabel = "v1"

        # Text overlays
        text_chain = vlabel
        draw_parts: list[str] = []
        draw_parts.append(
            "drawtext=text='LIVE':fontsize=22:fontcolor=white:box=1:boxcolor=0xc1121f@0.85:"
            "boxborderw=8:x=w-text_w-28:y=28"
        )
        if segment.now_playing_text:
            np = _escape_drawtext(segment.now_playing_text[:80])
            draw_parts.append(
                f"drawtext=text='NOW  {_escape_drawtext(segment.kind.upper())}  ·  {np}':"
                f"fontsize=24:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=10:"
                f"x=28:y=h-text_h-36"
            )
        prog = _escape_drawtext(segment.programme[:60])
        draw_parts.append(
            f"drawtext=text='{prog}':fontsize=20:fontcolor=white@0.9:"
            f"x=28:y=28"
        )
        draw_parts.append(
            "drawtext=text='%{localtime\\:%H\\\\:%M}':fontsize=22:fontcolor=white@0.9:"
            "x=w-text_w-28:y=h-text_h-36"
        )
        filters.append(f"[{text_chain}]{','.join(draw_parts)}[vout]")

        # Audio normalize
        filters.append(
            f"[{audio_idx}:a]aformat=sample_fmts=fltp:sample_rates={s.audio_rate}:"
            f"channel_layouts=stereo,volume=1.0[aout]"
        )

        cmd += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]"]

        # For native/video with its own duration, trim to audio/video length
        cmd += ["-t", f"{duration:.3f}"]

        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            s.preset,
            "-tune",
            "zerolatency",
            "-b:v",
            s.video_bitrate,
            "-maxrate",
            s.video_bitrate,
            "-bufsize",
            "4000k",
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(s.gop),
            "-keyint_min",
            str(s.gop),
            "-sc_threshold",
            "0",
            "-c:a",
            "aac",
            "-b:a",
            s.audio_bitrate,
            "-ar",
            str(s.audio_rate),
            "-ac",
            "2",
            "-f",
            "mpegts",
            "pipe:1",
        ]
        return cmd

    def run(self, segment: BroadcastSegment) -> subprocess.Popen[bytes]:
        cmd = self.build_command(segment)
        log.debug("Composer cmd: %s", " ".join(shlex.quote(c) for c in cmd))
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

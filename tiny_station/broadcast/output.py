from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from tiny_station.config import ROOT, StreamSettings

log = logging.getLogger(__name__)


class StreamOutput:
    """
    Persistent sink that keeps a continuous outbound connection alive.

    Architecture choice (see ARCHITECTURE.md):
    - Segment composers write normalized MPEG-TS into a FIFO.
    - One long-lived FFmpeg process reads that FIFO and either:
      * copies to RTMP (Restream / YouTube / etc.), or
      * writes a local preview file for cupboard testing.
    """

    def __init__(self, stream: StreamSettings, data_dir: Path) -> None:
        self.stream = stream
        self.data_dir = data_dir
        self.fifo_path = data_dir / "broadcast.fifo"
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.last_error = ""

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc and self._proc.poll() is None else None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def local_path(self) -> Path:
        out = Path(self.stream.local_output)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        return out

    def target_label(self) -> str:
        dest = self.stream.rtmp_destination()
        if dest:
            if "/" in dest:
                base, _, tail = dest.rpartition("/")
                if len(tail) > 6:
                    return f"{base}/{'*' * 6}{tail[-4:]}"
            return dest
        return f"file:{self.local_path()}"

    def prepare_fifo(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.fifo_path.exists():
            if not self.fifo_path.is_fifo():
                self.fifo_path.unlink()
                os.mkfifo(self.fifo_path)
        else:
            os.mkfifo(self.fifo_path)
        return self.fifo_path

    def start(self) -> None:
        with self._lock:
            if self.alive:
                return
            self.prepare_fifo()
            dest = self.stream.rtmp_destination()
            s = self.stream
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
            ]
            # Pace RTMP in realtime so platforms receive a live stream.
            # Local preview runs unpaced so smoke tests finish quickly;
            # FIFO backpressure still applies if the sink is slow.
            if dest:
                cmd.append("-re")
            cmd += [
                "-fflags",
                "+genpts+igndts",
                "-f",
                "mpegts",
                "-i",
                str(self.fifo_path),
            ]
            if dest:
                # Light restamp/re-encode keeps RTMP timestamps monotonic across
                # segment boundaries (copy-mode shows discontinuities in logs).
                cmd += [
                    "-vf",
                    f"fps={s.fps},format=yuv420p",
                    "-af",
                    f"aresample=async=1:first_pts=0,aformat=sample_rates={s.audio_rate}:channel_layouts=stereo",
                    "-c:v",
                    "libx264",
                    "-preset",
                    s.preset,
                    "-tune",
                    "zerolatency",
                    "-b:v",
                    s.video_bitrate,
                    "-g",
                    str(s.gop),
                    "-c:a",
                    "aac",
                    "-b:a",
                    s.audio_bitrate,
                    "-ar",
                    str(s.audio_rate),
                    "-f",
                    "flv",
                    dest,
                ]
                log.info("Stream output → RTMP %s", self.target_label())
            else:
                out = self.local_path()
                cmd += ["-c", "copy", "-f", "mpegts", str(out)]
                log.info("Stream output → local file %s", out)

            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, name="stream-stderr", daemon=True
            )
            self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            self.last_error = line
            log.warning("encoder: %s", line)

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def ensure_alive(self) -> bool:
        if self.alive:
            return True
        log.warning("Stream encoder died — restarting")
        time.sleep(0.5)
        self.start()
        return self.alive

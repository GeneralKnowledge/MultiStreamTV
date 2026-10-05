from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from tiny_station.broadcast.composer import SegmentComposer
from tiny_station.broadcast.output import StreamOutput
from tiny_station.config import StationConfig
from tiny_station.logging_util import get_ring
from tiny_station.media.indexer import MediaLibrary
from tiny_station.models import BroadcastStatus, StationState
from tiny_station.programme.engine import ProgrammeEngine

log = logging.getLogger(__name__)


class BroadcastEngine:
    """
    Orchestrates: ProgrammeEngine → Composer → FIFO → StreamOutput.

    Never intentionally terminates because one media item failed.
    """

    def __init__(self, config: StationConfig) -> None:
        self.config = config
        self.library = MediaLibrary(config.media_path, rescan_seconds=config.rescan_seconds)
        self.programme = ProgrammeEngine(self.library, config)
        self.composer = SegmentComposer(config.stream, station_name=config.station_name)
        self.output = StreamOutput(config.stream, config.data_path)
        self.state = StationState()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._fifo_fh = None

    def start(self, background: bool = True) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.library.scan(force=True)
        self.state.status = BroadcastStatus.STARTING
        self.state.started_at = time.time()
        self.state.stream_target = self.output.target_label()
        if background:
            self._thread = threading.Thread(target=self._run, name="broadcast", daemon=True)
            self._thread.start()
        else:
            self._run()

    def stop(self) -> None:
        self._stop.set()
        if self._fifo_fh is not None:
            try:
                self._fifo_fh.close()
            except OSError:
                pass
            self._fifo_fh = None
        self.output.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=8)
        self.state.status = BroadcastStatus.STOPPED
        self.state.stream_healthy = False
        log.info("Broadcast stopped")

    def status_dict(self) -> dict:
        self.state.recent_log = get_ring().lines()
        self.state.encoder_pid = self.output.pid
        self.state.stream_healthy = self.output.alive and self.state.status in {
            BroadcastStatus.BROADCASTING,
            BroadcastStatus.FALLBACK,
        }
        return self.state.to_dict()

    def _open_fifo_writer(self) -> None:
        # Start reader first (encoder), then open writer — classic FIFO handshake.
        self.output.start()
        path = self.output.fifo_path
        log.info("Opening broadcast FIFO %s", path)

        def _open() -> None:
            # This blocks until the encoder opens the read end.
            self._fifo_fh = open(path, "wb", buffering=0)

        opener = threading.Thread(target=_open, name="fifo-open", daemon=True)
        opener.start()
        opener.join(timeout=15)
        if self._fifo_fh is None:
            raise RuntimeError("Timed out opening FIFO writer — is the encoder running?")

    def _run(self) -> None:
        log.info("Starting station: %s", self.config.station_name)
        try:
            self._open_fifo_writer()
        except Exception as exc:  # noqa: BLE001
            self.state.status = BroadcastStatus.ERROR
            self.state.last_error = str(exc)
            log.error("Failed to start stream: %s", exc)
            return

        self.state.status = BroadcastStatus.BROADCASTING
        log.info("Broadcasting")

        while not self._stop.is_set():
            try:
                if not self.output.ensure_alive():
                    self.state.status = BroadcastStatus.RECOVERING
                    self._reopen_pipeline()
                    continue

                upcoming = self.programme.peek_next()
                if upcoming:
                    self.state.next = upcoming.label()
                    self.state.next_kind = upcoming.kind

                segment = self.programme.next_segment()
                self.state.programme = segment.programme
                self.state.now = segment.label()
                self.state.now_kind = segment.kind
                self.state.segment_started_at = time.time()
                self.state.status = (
                    BroadcastStatus.FALLBACK if segment.is_fallback else BroadcastStatus.BROADCASTING
                )

                if segment.kind == "fallback":
                    log.warning("fallback visual activated")
                log.info("Starting programme block: %s", segment.programme)
                log.info("Playing: %s (%s)", segment.label(), segment.kind)
                if segment.video:
                    log.info(
                        "Visual: %s [%s]",
                        Path(segment.video.path).name,
                        segment.visual_mode.value,
                    )

                self._pump_segment(segment)
                self.state.segments_played += 1

                nxt = self.programme.peek_next()
                if nxt:
                    self.state.next = nxt.label()
                    self.state.next_kind = nxt.kind
                    log.info("Next: %s", nxt.label())

            except Exception as exc:  # noqa: BLE001
                self.state.failures += 1
                self.state.last_error = str(exc)
                self.state.status = BroadcastStatus.RECOVERING
                log.error("segment failed: %s", exc)
                log.info("continuing broadcast")
                time.sleep(1.0)

        self.output.stop()

    def _reopen_pipeline(self) -> None:
        if self._fifo_fh is not None:
            try:
                self._fifo_fh.close()
            except OSError:
                pass
            self._fifo_fh = None
        self.output.stop()
        time.sleep(0.5)
        try:
            self._open_fifo_writer()
            self.state.status = BroadcastStatus.BROADCASTING
            log.info("Pipeline reopened")
        except Exception as exc:  # noqa: BLE001
            self.state.last_error = str(exc)
            log.error("Pipeline reopen failed: %s", exc)
            time.sleep(2.0)

    def _pump_segment(self, segment) -> None:
        if self._fifo_fh is None:
            raise RuntimeError("FIFO writer is not open")
        proc = self.composer.run(segment)
        assert proc.stdout is not None
        try:
            while not self._stop.is_set():
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                fh = self._fifo_fh
                if fh is None or self._stop.is_set():
                    break
                try:
                    fh.write(chunk)
                except BrokenPipeError:
                    log.warning("FIFO broken pipe — recovering")
                    self._reopen_pipeline()
                    break
            if not self._stop.is_set():
                proc.wait(timeout=5)
        finally:
            if proc.poll() is None:
                proc.kill()
            err = b""
            if proc.stderr:
                try:
                    err = proc.stderr.read()
                except Exception:  # noqa: BLE001
                    err = b""
            if self._stop.is_set():
                return
            if proc.returncode not in (0, None):
                msg = err.decode("utf-8", errors="replace").strip() or f"exit {proc.returncode}"
                # SIGPIPE / kill during recovery is not a media failure
                if proc.returncode in (-13, 141, 255) and not msg:
                    return
                self.state.failures += 1
                self.state.last_error = msg
                log.warning("video segment failed: %s", msg[:300])
                raise RuntimeError(msg)

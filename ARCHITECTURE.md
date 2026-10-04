# Architecture notes

Investigation answers that shaped the MVP.

## 1. Is FFmpeg alone sufficient?

**Yes for MVP.** FFmpeg can compose audio + looping video + overlays + text, encode H.264/AAC, and push RTMP. The project needs mixed media (MP3/MP4/images/overlays), which fits FFmpeg better than an audio-first tool.

## 2. Does Liquidsoap justify inclusion?

**Not for MVP.** Liquidsoap is excellent for internet radio scheduling, but weaker as a general A/V compositor for independent audio/video layers, image slides, and overlays. Keep it optional later for audio-only modes if desired.

## 3. Concatenating heterogeneous media

Normalize **per segment** to a common MPEG-TS (H.264 + AAC, fixed size/fps/sample rate), then concatenate by writing those packets into one pipe. Avoid demux-level concat of raw source files with mismatched codecs.

## 4. Continuous timestamps

Segment composer emits clean TS. The persistent output process uses `-fflags +genpts+igndts` so discontinuities between segments do not kill the sink.

## 5. Switching segments without dropping RTMP

One long-lived FFmpeg process owns the RTMP connection and reads a FIFO. Segment composers write into that FIFO sequentially. The public stream stays up across segment boundaries.

## 6. Recovering from FFmpeg crashes

`BroadcastEngine` watches the output process. On death: close FIFO, restart encoder, reopen writer, continue from the next segment / fallback. Segment failures increment a counter and activate fallback media instead of exiting.

## 7. VPS resources

Target: 1 vCPU, 512MB–1GB RAM, no GPU.

Practical defaults:
- 1280×720 @ 30fps
- ~1.5–2 Mbps video, `ultrafast` / `zerolatency`
- 128 kbps AAC
- Prefer short segments and lightweight overlays

Pre-normalising large libraries helps; MVP re-encodes per segment for robustness.

## 8. Persistent FFmpeg vs one process per segment

**Hybrid (chosen):**
- **Composer**: one FFmpeg process per segment → MPEG-TS stdout
- **Output**: one persistent FFmpeg process → RTMP or local file

One process per segment *directly* to RTMP would reconnect every song and look broken on Twitch/YouTube.

## 9. Incompatible MP4 codecs

`ffprobe` on index. Failures mark assets with notes. At play time, composer re-encodes to H.264/AAC. `tiny-station validate` surfaces problems early.

## 10. Broadcast queue

`ProgrammeEngine` maintains a small lookahead deque of `BroadcastSegment`s. Modes:
- **structure**: cycle a declared sequence
- **weighted**: procedural picks with anti-repeat memory

`BroadcastEngine` consumes forever.

## Separation of concerns

```
MediaLibrary        → what files exist?
ProgrammeEngine     → what should happen next?
SegmentComposer     → how are A/V/overlays combined?
StreamOutput        → where does the encoded stream go?
BroadcastEngine     → glue + recovery + state
```

## What is intentionally not here

User accounts, databases, multi-tenant CMS, analytics, direct multi-platform fan-out, Liquidsoap, GPU effects, AI programming (future plan consumer only).

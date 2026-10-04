# Tiny Station

A cupboard-sized autonomous television/radio station.

Drop media into a folder. The server endlessly assembles it into a coherent-looking broadcast and sends **one** outbound stream (RTMP → Restream / YouTube / Twitch / Kick, or a local preview file).

This is deliberately **not** a radio-management platform. The filesystem is the media library.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Check the sample media
tiny-station validate
tiny-station scan

# Run broadcast + status UI (http://localhost:8080)
tiny-station run
```

With no `STREAM_URL` set, output goes to `data/preview/broadcast.ts` (playable in VLC).

### Point at Restream / YouTube

```bash
export STREAM_URL=rtmp://live.restream.io/live
export STREAM_KEY=your_key_here
tiny-station run
```

Or edit `config/station.yaml`.

### The walk-away workflow

```bash
cp my-song.mp3 media/music/
cp weird-video.mp4 media/video/
cp logo.png media/images/
tiny-station run
```

Walk away. The station keeps going.

## Media layout

```
media/
  music/           # songs (mp3/wav/…)
  video/           # films / clips with their own audio
  visuals/         # looping backgrounds
  images/          # stills + logo.png
  jingles/         # idents / stings
  announcements/   # voice drops
  _fallback/       # standby media if something breaks
```

Files are discovered automatically from directory + extension + light probing. No CMS required.

## What the MVP does

- Filesystem media discovery (`MediaLibrary`)
- Weighted + structured programmes (`ProgrammeEngine`)
- Independent audio / video / overlay composition via FFmpeg
- Persistent RTMP (or local) output without reconnecting every segment
- Automatic fallback + recovery
- Tiny status / upload web UI + JSON API

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design decisions (FFmpeg vs Liquidsoap, FIFO encoder, etc.).

## Commands

| Command | Purpose |
|--------|---------|
| `tiny-station run` | Broadcast + web UI |
| `tiny-station run --no-web` | Broadcast only |
| `tiny-station validate` | Probe media, flag problems |
| `tiny-station scan` | List indexed assets |

## API

- `GET /api/status` — now / next / uptime / health
- `GET /api/media` — library
- `POST /api/upload` — multipart upload (`category`, `file`)
- `POST /api/rescan` — force rescan

## Config

`config/station.yaml` — station name, stream settings, programmes, schedule.

Programmes can be:

- **weighted** — e.g. 70% music, 12% video, 8% ident…
- **structure** — fixed sequences like `ident → music → music → announcement → video`

Schedule example (with always-on fallback programme):

```yaml
schedule:
  "00:00": { programme: late-night }
  "06:00": { programme: autonomous }
  "22:00": { programme: late-night }
```

## Resource target

Designed for a cheap Linux VPS (~1 vCPU, 512MB–1GB RAM, no GPU). Default encode: 720p30, ~1.5 Mbps, `ultrafast`.

## Roadmap (not in this MVP)

Transitions beyond hard cuts, richer overlays, generated waveforms, day/night themes, LLM-written programme plans, synthetic presenters, multi-station hosting.

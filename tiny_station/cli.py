from __future__ import annotations

import argparse
import signal
import sys
import time

import uvicorn

from tiny_station.config import load_config
from tiny_station.logging_util import setup_logging
from tiny_station.media.probe import ensure_ffmpeg
from tiny_station.station import Station


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tiny-station",
        description="Tiny self-hosted autonomous television/radio station",
    )
    p.add_argument(
        "-c",
        "--config",
        default=None,
        help="Path to station.yaml (default: config/station.yaml)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Start broadcast + web UI")
    run.add_argument("--no-web", action="store_true", help="Broadcast only")
    run.add_argument("--no-broadcast", action="store_true", help="Web UI only")

    sub.add_parser("validate", help="Validate media library with ffprobe")
    sub.add_parser("scan", help="Scan and list discovered media")
    sub.add_parser("status", help="Print current status JSON (requires running state file — use API)")

    return p


def cmd_validate(station: Station) -> int:
    rows = station.broadcast.library.validate()
    if not rows:
        print("No media found under", station.config.media_path)
        return 1
    for row in rows:
        print(f"{row['mark']} {row['path']} — {row['detail']}")
    bad = sum(1 for r in rows if r["mark"] != "✓")
    print(f"\n{len(rows)} files, {bad} warnings")
    return 0 if bad == 0 else 2


def cmd_scan(station: Station) -> int:
    assets = station.broadcast.library.scan(force=True)
    for a in assets:
        dur = f"{a.duration:.1f}s" if a.duration else "?"
        print(f"{a.category.value:14} {dur:>8}  {a.title}  ({a.path})")
    print(f"\n{len(assets)} assets")
    return 0


def cmd_run(station: Station, no_web: bool, no_broadcast: bool) -> int:
    ensure_ffmpeg()
    setup_logging(station.config.data_path / "logs")

    if not no_broadcast:
        station.start(background=True)

    if no_web:
        def _stop(signum, frame):  # noqa: ARG001
            station.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        print(f"Broadcasting as {station.config.station_name}. Ctrl+C to stop.")
        while True:
            time.sleep(1)

    app = None
    from tiny_station.web.app import create_app

    app = create_app(station)

    def _on_exit() -> None:
        station.stop()

    # uvicorn handles signals; ensure broadcast stops after server exits
    try:
        uvicorn.run(
            app,
            host=station.config.web_host,
            port=station.config.web_port,
            log_level="info",
        )
    finally:
        _on_exit()
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    station = Station(config)

    if args.command == "validate":
        raise SystemExit(cmd_validate(station))
    if args.command == "scan":
        raise SystemExit(cmd_scan(station))
    if args.command == "status":
        print("Use GET /api/status on the running web UI.")
        raise SystemExit(0)
    if args.command == "run":
        raise SystemExit(cmd_run(station, args.no_web, args.no_broadcast))
    parser.error(f"Unknown command {args.command}")


if __name__ == "__main__":
    main()

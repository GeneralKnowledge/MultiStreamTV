from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from tiny_station import __version__
from tiny_station.station import Station

CATEGORY_DIRS = {
    "music": "music",
    "video": "video",
    "visual": "visuals",
    "jingle": "jingles",
    "ident": "jingles",
    "announcement": "announcements",
    "image": "images",
}


def create_app(station: Station) -> FastAPI:
    app = FastAPI(title=station.config.station_name, version=__version__)
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/status")
    async def api_status() -> dict:
        return station.status()

    @app.get("/api/media")
    async def api_media() -> dict:
        assets = [a.to_dict() for a in station.broadcast.library.scan()]
        return {"count": len(assets), "assets": assets}

    @app.get("/api/programmes")
    async def api_programmes() -> dict:
        return {
            key: prog.model_dump() for key, prog in station.config.programmes.items()
        }

    @app.get("/api/schedule")
    async def api_schedule() -> dict:
        return {
            stamp: slot.model_dump() for stamp, slot in station.config.schedule.items()
        }

    @app.post("/api/upload")
    async def api_upload(
        category: str = Form(...),
        file: UploadFile = File(...),
    ) -> dict:
        cat = category.lower().strip()
        if cat not in CATEGORY_DIRS:
            raise HTTPException(400, f"Unknown category: {category}")
        if not file.filename:
            raise HTTPException(400, "Missing filename")
        dest_dir = station.config.media_path / CATEGORY_DIRS[cat]
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(file.filename).name
        dest = dest_dir / safe_name
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        station.broadcast.library.scan(force=True)
        return {"ok": True, "path": str(dest.relative_to(station.config.media_path))}

    @app.post("/api/rescan")
    async def api_rescan() -> dict:
        assets = station.broadcast.library.scan(force=True)
        return {"ok": True, "count": len(assets)}

    @app.get("/api/health")
    async def api_health() -> dict:
        status = station.status()
        return {
            "ok": status.get("status") in {"broadcasting", "fallback", "starting"},
            "status": status.get("status"),
            "version": __version__,
        }

    return app

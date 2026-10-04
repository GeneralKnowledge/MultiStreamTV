from pathlib import Path

from tiny_station.config import load_config
from tiny_station.media.indexer import MediaLibrary
from tiny_station.programme.engine import ProgrammeEngine


def test_library_scans_sample_media():
    cfg = load_config()
    lib = MediaLibrary(cfg.media_path, rescan_seconds=0)
    assets = lib.scan(force=True)
    assert len(assets) >= 5
    cats = {a.category.value for a in assets}
    assert "music" in cats


def test_programme_generates_segments():
    cfg = load_config()
    lib = MediaLibrary(cfg.media_path, rescan_seconds=0)
    lib.scan(force=True)
    engine = ProgrammeEngine(lib, cfg)
    seg = engine.next_segment()
    assert seg.programme
    assert seg.kind
    assert seg.audio is not None or seg.video is not None


def test_validate_marks_ok():
    cfg = load_config()
    lib = MediaLibrary(cfg.media_path, rescan_seconds=0)
    rows = lib.validate()
    assert rows
    assert any(r["mark"] == "✓" for r in rows)

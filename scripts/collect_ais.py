"""Optional AIS collector — live vessel positions for watched maritime zones.

AISStream.io gives a FREE real-time WebSocket. Because it's a *stream* (not a
poll), this runs for a bounded number of seconds, captures the latest position
per vessel in each configured zone, writes them to SQLite, then exits — which
makes it fit a timed job or a manual local run.

Setup:
  1. Get a free key at https://aisstream.io  ->  put it in .env as AISSTREAM_API_KEY
  2. Define zones in config.yaml under `ais:`
  3. Run:  python scripts/collect_ais.py

Caveat that matters: AISStream is terrestrial AIS. Coverage in open ocean is
patchy, so a low vessel count in mid-strait is NOT proof the strait is empty.
Never read a coverage gap as an event.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from osint import db  # noqa: E402
from osint.collect import load_config  # noqa: E402

STREAM_URL = "wss://stream.aisstream.io/v0/stream"


def _in_bbox(lat: float, lon: float, bbox: list) -> bool:
    (lat_min, lon_min), (lat_max, lon_max) = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def position_from_message(msg: dict, zones: list[dict]) -> dict | None:
    """Pure parser (unit-testable). Map an AISStream message to a position row,
    tagged with the first configured zone whose bbox contains it."""
    if msg.get("MessageType") != "PositionReport":
        return None
    report = msg.get("Message", {}).get("PositionReport", {})
    meta = msg.get("MetaData", {})
    lat, lon = report.get("Latitude"), report.get("Longitude")
    if lat is None or lon is None:
        return None
    zone_name = None
    for z in zones:
        if _in_bbox(lat, lon, z["bbox"]):
            zone_name = z["name"]
            break
    if zone_name is None:
        return None
    return {
        "mmsi": str(meta.get("MMSI") or report.get("UserID") or ""),
        "name": (meta.get("ShipName") or "").strip() or None,
        "zone": zone_name,
        "lat": lat,
        "lon": lon,
        "sog": report.get("Sog"),
        "cog": report.get("Cog"),
    }


async def _collect(api_key: str, zones: list[dict], duration: int) -> dict[str, dict]:
    import websockets  # imported here so the script only needs it when run

    # AISStream wants boxes as [[[lat,lon],[lat,lon]], ...]
    boxes = [[z["bbox"][0], z["bbox"][1]] for z in zones]
    sub = {
        "APIKey": api_key,
        "BoundingBoxes": boxes,
        "FilterMessageTypes": ["PositionReport"],
    }
    latest: dict[str, dict] = {}  # key: mmsi|zone -> row
    try:
        async with websockets.connect(STREAM_URL, ping_interval=None) as ws:
            await ws.send(json.dumps(sub))
            print(f"[ais] subscribed to {len(zones)} zone(s); "
                  f"listening {duration}s ...")
            try:
                async with asyncio.timeout(duration):
                    async for raw in ws:
                        row = position_from_message(json.loads(raw), zones)
                        if row and row["mmsi"]:
                            latest[f"{row['mmsi']}|{row['zone']}"] = row
            except asyncio.TimeoutError:
                pass
    except Exception as exc:  # noqa: BLE001
        print(f"[ais] stream error: {exc}")
    return latest


def main() -> int:
    cfg = load_config()
    ac = cfg.get("ais", {})
    if not ac.get("enabled", False):
        print("[ais] disabled in config.yaml (ais.enabled: false). Skipping.")
        return 0
    api_key = os.environ.get("AISSTREAM_API_KEY")
    if not api_key:
        print("[ais] no AISSTREAM_API_KEY set. Get a free key at aisstream.io.")
        return 0
    zones = ac.get("zones", [])
    if not zones:
        print("[ais] no zones configured under ais.zones. Skipping.")
        return 0

    duration = int(ac.get("duration_seconds", 60))
    latest = asyncio.run(_collect(api_key, zones, duration))

    conn = db.connect()
    db.init_db(conn)
    n = db.upsert_ais_positions(conn, list(latest.values()))
    conn.close()
    print(f"[ais] stored {n} vessel positions across {len(zones)} zone(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Orchestrator. Reads config, runs every enabled source, stores new events,
records market probabilities, and runs signal detection.

This is the function the frequent GitHub Actions job calls. It makes NO LLM
calls — synthesis lives in the separate once-a-day brief job, so this stays free.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import db, signals
from .sources import GDELTSource, MarketsSource, RSSSource

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_sources(cfg: dict) -> list:
    sources: list = []
    if cfg.get("rss", {}).get("enabled", True):
        feeds = cfg.get("rss", {}).get("feeds", [])
        if feeds:
            sources.append(RSSSource(feeds))
    if cfg.get("gdelt", {}).get("enabled", True):
        g = cfg.get("gdelt", {})
        if g.get("queries"):
            sources.append(
                GDELTSource(
                    g["queries"],
                    timespan=g.get("timespan", "1h"),
                    max_records=g.get("max_records", 75),
                )
            )
    if cfg.get("markets", {}).get("enabled", False):
        m = cfg.get("markets", {})
        sources.append(
            MarketsSource(
                keywords=m.get("keywords", []),
                limit=m.get("limit", 40),
                min_volume=m.get("min_volume", 0.0),
            )
        )
    return sources


def run() -> int:
    cfg = load_config()
    conn = db.connect()
    db.init_db(conn)

    total_new = 0
    for source in build_sources(cfg):
        name = source.__class__.__name__
        print(f"[collect] running {name} ...")
        events = source.collect()
        new = db.upsert_events(conn, events)
        total_new += new
        # markets carry a probability side-channel for the history table
        snaps = getattr(source, "snapshots", None)
        if snaps:
            db.record_market_snapshots(conn, snaps)
            print(f"[collect] {name}: recorded {len(snaps)} market snapshots")
        print(f"[collect] {name}: +{new} new events")

    # cross-source signal detection (cheap, no LLM)
    signals.run(conn, cfg)

    print(f"[collect] DONE — {total_new} new events stored")
    conn.close()
    return total_new


if __name__ == "__main__":
    run()

"""Prediction-market collector — Polymarket + Manifold (free, no auth).

Prediction markets are a leading indicator: a sharp probability move often
precedes the news catching up. We do two things with them:
  1. Emit each tracked market as an Event (so it shows in the feed).
  2. Record its probability into market_history, so signals.py can detect swings.

Kalshi and Metaculus are intentionally left as extension points below — Kalshi
needs RSA-key auth and Metaculus a bit more parsing, so they're opt-in later.
Polymarket and Manifold require nothing but an HTTP GET.
"""
from __future__ import annotations

import json
from typing import Any

import requests

from ..models import Event
from ..normalize import tag
from .base import Source

POLYMARKET_API = "https://gamma-api.polymarket.com/markets"
MANIFOLD_API = "https://api.manifold.markets/v0/markets"
UA = {"User-Agent": "personal-osint/1.0"}


def _as_list(value: Any) -> list:
    """Polymarket returns some fields as JSON-encoded strings; be tolerant."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _keyword_match(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    t = text.lower()
    return any(k.lower() in t for k in keywords)


# --------------------------------------------------------------------------- #
# pure parsers (unit-testable without network)
# --------------------------------------------------------------------------- #
def parse_polymarket_market(m: dict) -> dict | None:
    """-> snapshot dict {market_id, platform, question, probability, url, volume}
    or None if the market isn't usable (closed, no price, etc.)."""
    if m.get("closed") or m.get("archived"):
        return None
    question = (m.get("question") or "").strip()
    if not question:
        return None
    prices = _as_list(m.get("outcomePrices"))
    if not prices:
        return None
    try:
        prob = float(prices[0])  # price of the first outcome ~ its probability
    except (ValueError, TypeError):
        return None
    slug = m.get("slug") or ""
    url = f"https://polymarket.com/market/{slug}" if slug else "https://polymarket.com"
    try:
        volume = float(m.get("volume") or 0)
    except (ValueError, TypeError):
        volume = 0.0
    return {
        "market_id": f"pm:{m.get('id') or slug}",
        "platform": "Polymarket",
        "question": question,
        "probability": prob,
        "url": url,
        "volume": volume,
    }


def parse_manifold_market(m: dict) -> dict | None:
    if m.get("isResolved"):
        return None
    if m.get("outcomeType") != "BINARY":
        return None
    question = (m.get("question") or "").strip()
    prob = m.get("probability")
    if not question or prob is None:
        return None
    try:
        volume = float(m.get("volume24Hours") or m.get("volume") or 0)
    except (ValueError, TypeError):
        volume = 0.0
    return {
        "market_id": f"mf:{m.get('id')}",
        "platform": "Manifold",
        "question": question,
        "probability": float(prob),
        "url": m.get("url") or "https://manifold.markets",
        "volume": volume,
    }


def snapshot_to_event(s: dict) -> Event:
    pct = round(s["probability"] * 100)
    region, topics = tag(s["question"])
    topics = ", ".join(filter(None, [topics, "market"]))
    return Event(
        source=f"Market/{s['platform']}",
        source_type="market",
        title=s["question"],
        url=s["url"],
        summary=f"{pct}% implied probability · {s['platform']}",
        published_at=None,
        region=region,
        topics=topics,
        raw="",
    )


# --------------------------------------------------------------------------- #
# source
# --------------------------------------------------------------------------- #
class MarketsSource(Source):
    source_type = "market"

    def __init__(
        self,
        keywords: list[str] | None = None,
        limit: int = 40,
        min_volume: float = 0.0,
    ):
        self.keywords = keywords or []
        self.limit = limit
        self.min_volume = min_volume
        # side-channel the orchestrator reads to write market_history
        self.snapshots: list[dict] = []

    def _fetch_polymarket(self) -> list[dict]:
        params = {"active": "true", "closed": "false",
                  "order": "volume", "ascending": "false", "limit": 150}
        resp = requests.get(POLYMARKET_API, params=params, headers=UA, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        markets = data if isinstance(data, list) else data.get("data", [])
        out = []
        for m in markets:
            s = parse_polymarket_market(m)
            if s and _keyword_match(s["question"], self.keywords):
                out.append(s)
        return out

    def _fetch_manifold(self) -> list[dict]:
        resp = requests.get(MANIFOLD_API, params={"limit": 200}, headers=UA, timeout=30)
        resp.raise_for_status()
        out = []
        for m in resp.json():
            s = parse_manifold_market(m)
            if s and _keyword_match(s["question"], self.keywords):
                out.append(s)
        return out

    def collect(self) -> list[Event]:
        snapshots: list[dict] = []
        for name, fetch in (("polymarket", self._fetch_polymarket),
                            ("manifold", self._fetch_manifold)):
            try:
                got = fetch()
                snapshots.extend(got)
                print(f"  [market] {name}: {len(got)} matched")
            except Exception as exc:  # noqa: BLE001 — one platform down != run dead
                print(f"  [market] FAILED {name}: {exc}")

        snapshots = [s for s in snapshots if s["volume"] >= self.min_volume]
        snapshots.sort(key=lambda s: s["volume"], reverse=True)
        snapshots = snapshots[: self.limit]

        self.snapshots = snapshots  # picked up by the orchestrator
        return [snapshot_to_event(s) for s in snapshots]

"""The single common schema every source normalizes into.

Keeping one Event shape is what lets the dashboard, dedup, and (later) the
LLM synthesis layer treat all sources identically.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_id(url: str | None, title: str, source: str) -> str:
    """Stable id used for deduplication.

    Prefer the URL (most reliable). Fall back to title+source so items
    without a clean URL still dedupe sensibly.
    """
    basis = (url or f"{source}:{title}").strip().lower()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


@dataclass
class Event:
    source: str            # e.g. "BBC World", "GDELT"
    source_type: str       # "rss" | "gdelt" | "market" | "ais" ...
    title: str
    url: str | None = None
    summary: str = ""
    published_at: str | None = None  # ISO 8601 if known
    region: str = ""                 # coarse tag (Phase 1: keyword guess)
    topics: str = ""                 # comma-separated coarse tags
    raw: str = ""                    # original blob for debugging
    collected_at: str = field(default_factory=_now)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = make_id(self.url, self.title, self.source)

    def as_row(self) -> dict:
        return asdict(self)

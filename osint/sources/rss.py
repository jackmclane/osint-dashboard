"""RSS / Atom collector. Free, structured, no scraping.

Covers most international publications and government press-release feeds.
"""
from __future__ import annotations

from datetime import datetime, timezone
from time import mktime

import feedparser

from ..models import Event
from ..normalize import tag
from .base import Source


class RSSSource(Source):
    source_type = "rss"

    def __init__(self, feeds: list[dict]):
        # each feed: {"name": "...", "url": "..."}
        self.feeds = feeds

    def _published(self, entry) -> str | None:
        for key in ("published_parsed", "updated_parsed"):
            t = getattr(entry, key, None)
            if t:
                return datetime.fromtimestamp(mktime(t), tz=timezone.utc).isoformat()
        return None

    def collect(self) -> list[Event]:
        events: list[Event] = []
        for feed in self.feeds:
            url = feed["url"]
            name = feed.get("name", url)
            try:
                parsed = feedparser.parse(url)
            except Exception as exc:  # noqa: BLE001 — never let one feed kill the run
                print(f"  [rss] FAILED {name}: {exc}")
                continue
            for entry in parsed.entries:
                title = getattr(entry, "title", "").strip()
                if not title:
                    continue
                link = getattr(entry, "link", None)
                summary = getattr(entry, "summary", "")[:600]
                region, topics = tag(title, summary)
                events.append(
                    Event(
                        source=name,
                        source_type=self.source_type,
                        title=title,
                        url=link,
                        summary=summary,
                        published_at=self._published(entry),
                        region=region,
                        topics=topics,
                        raw="",
                    )
                )
            print(f"  [rss] {name}: {len(parsed.entries)} entries")
        return events

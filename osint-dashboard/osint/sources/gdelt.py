"""GDELT 2.0 DOC API collector — your free global-news backbone.

Queries the public DOC API (no key required) for each configured topic query
and returns recent articles. Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from ..models import Event
from ..normalize import tag
from .base import Source

API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _parse_seendate(s: str) -> str | None:
    # GDELT format: 20260628T120000Z
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        ).isoformat()
    except (ValueError, TypeError):
        return None


class GDELTSource(Source):
    source_type = "gdelt"

    def __init__(self, queries: list[dict], timespan: str = "1h",
                 max_records: int = 75):
        # each query: {"label": "maritime", "query": "(strait OR vessel)"}
        self.queries = queries
        self.timespan = timespan
        self.max_records = max_records

    def collect(self) -> list[Event]:
        events: list[Event] = []
        for q in self.queries:
            label, query = q.get("label", ""), q["query"]
            params = {
                "query": query,
                "mode": "artlist",
                "format": "json",
                "maxrecords": self.max_records,
                "timespan": self.timespan,
                "sort": "datedesc",
            }
            try:
                resp = requests.get(API, params=params, timeout=30,
                                    headers={"User-Agent": "personal-osint/0.1"})
                resp.raise_for_status()
                articles = resp.json().get("articles", [])
            except Exception as exc:  # noqa: BLE001
                print(f"  [gdelt] FAILED {label}: {exc}")
                continue
            for a in articles:
                title = (a.get("title") or "").strip()
                if not title:
                    continue
                region, topics = tag(title)
                # fold the query label in as a topic hint
                topics = ", ".join(filter(None, [topics, label]))
                events.append(
                    Event(
                        source=f"GDELT/{a.get('domain', '?')}",
                        source_type=self.source_type,
                        title=title,
                        url=a.get("url"),
                        summary="",
                        published_at=_parse_seendate(a.get("seendate", "")),
                        region=region or (a.get("sourcecountry") or ""),
                        topics=topics,
                        raw="",
                    )
                )
            print(f"  [gdelt] {label}: {len(articles)} articles")
        return events

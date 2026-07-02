"""Phase 2 — the daily brief. Your one piece of real synthesis.

Design goal: maximum value, minimum spend. This runs ONCE a day (separate
workflow) and makes at most ONE LLM call. With Haiku that's a fraction of a
cent per day — comfortably inside a sub-$10 budget even if you run it hourly.

If no ANTHROPIC_API_KEY is set, it falls back to a no-LLM digest so the whole
project still works for $0. Set the key to upgrade the brief to real prose.
"""
from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db

BRIEF_DIR = Path(__file__).resolve().parent.parent / "data" / "briefs"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fetch(conn: sqlite3.Connection, hours: int, cap: int) -> list[sqlite3.Row]:
    since = (_now() - timedelta(hours=hours)).isoformat()
    rows = db.events_since(conn, since)
    return rows[:cap]


# --------------------------------------------------------------------------- #
# free fallback: a grouped digest, no LLM
# --------------------------------------------------------------------------- #
def render_digest(events: list, signals: list) -> str:
    today = _now().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# Daily Brief — {today}", ""]

    if signals:
        lines.append("## ⚠️ Signals to watch")
        for s in signals:
            row = f"- **{s['title']}** — {s['detail'] or ''}".rstrip(" —")
            lines.append(row)
        lines.append("")

    by_region: dict[str, list] = defaultdict(list)
    for e in events:
        by_region[(e["region"] or "Unsorted").split(",")[0].strip()].append(e)

    lines.append("## By region")
    for region in sorted(by_region, key=lambda r: -len(by_region[r])):
        items = by_region[region]
        lines.append(f"### {region} ({len(items)})")
        for e in items[:8]:
            src = e["source"]
            if e["url"]:
                lines.append(f"- [{e['title']}]({e['url']}) — *{src}*")
            else:
                lines.append(f"- {e['title']} — *{src}*")
        lines.append("")

    lines.append("---")
    lines.append("*No LLM key set — this is the free grouped digest. "
                 "Set `ANTHROPIC_API_KEY` for a synthesized brief.*")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# LLM brief: one call
# --------------------------------------------------------------------------- #
def _build_prompt(events: list, signals: list) -> str:
    sig_block = "\n".join(
        f"- [{s['kind']}] {s['title']} :: {s['detail'] or ''}" for s in signals
    ) or "(none detected)"

    ev_block = "\n".join(
        f"- ({e['source_type']}) [{e['region'] or '?'} | {e['topics'] or '-'}] "
        f"{e['title']} — {e['source']}"
        for e in events
    )

    return (
        "You are an OSINT analyst writing a concise morning intelligence brief "
        "for a single reader who tracks geopolitics, conflict, policy, and "
        "maritime events. Below are (1) automatically-detected signals and "
        "(2) raw collected items from the last 24h (news, and prediction "
        "markets shown with implied probabilities).\n\n"
        "Write a tight brief in Markdown with these sections:\n"
        "## Executive summary  (3-5 bullets, the day's most consequential threads)\n"
        "## By theatre  (group notable developments by region; be specific)\n"
        "## Market signals  (what the prediction-market moves imply)\n"
        "## Check manually on X  (3-6 specific things worth a human read, phrased "
        "as what to search or whose account to check — you do NOT have X access)\n\n"
        "Rules: synthesize and paraphrase in your own words; never reproduce "
        "headlines verbatim. Be skeptical — flag uncertainty and single-source "
        "claims. Do not invent facts not present below. Keep it scannable.\n\n"
        f"=== SIGNALS ===\n{sig_block}\n\n"
        f"=== COLLECTED ITEMS ({len(events)}) ===\n{ev_block}\n"
    )


def render_llm(events: list, signals: list, model: str) -> str | None:
    """Return a synthesized brief, or None if the SDK/key/call is unavailable."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        print("[brief] anthropic package not installed; using free digest")
        return None
    try:
        client = Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": _build_prompt(events, signals)}],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )
        header = f"# Daily Brief — {_now().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        return header + text.strip()
    except Exception as exc:  # noqa: BLE001 — never let the brief crash the run
        print(f"[brief] LLM call failed ({exc}); using free digest")
        return None


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def generate(conn: sqlite3.Connection, cfg: dict | None = None) -> tuple[Path, str]:
    cfg = cfg or {}
    bc = cfg.get("brief", {})
    events = _fetch(conn, hours=bc.get("window_hours", 24),
                    cap=bc.get("max_events", 120))
    signals = [dict(s) for s in db.recent_signals(conn, limit=15)]

    text = render_llm(events, signals, model=bc.get("model", "claude-haiku-4-5-20251001"))
    if text is None:
        text = render_digest(events, signals)

    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    path = BRIEF_DIR / f"brief_{_now().strftime('%Y-%m-%d')}.md"
    path.write_text(text, encoding="utf-8")
    # also keep a stable 'latest' pointer the dashboard can always find
    (BRIEF_DIR / "latest.md").write_text(text, encoding="utf-8")
    print(f"[brief] wrote {path.name} ({len(events)} events, {len(signals)} signals)")
    return path, text


if __name__ == "__main__":
    c = db.connect()
    db.init_db(c)
    generate(c)
    c.close()

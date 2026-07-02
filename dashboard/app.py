"""Streamlit dashboard — your read-only window into everything collected.

Run locally:   streamlit run dashboard/app.py
Deploy free:   push to GitHub, point Streamlit Community Cloud at this file.

Layout: a Signals strip up top (where to look now), then tabs for the raw Feed,
the Daily Brief, and the Maritime (AIS) picture.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from osint import db  # noqa: E402

BRIEF_DIR = Path(__file__).resolve().parent.parent / "data" / "briefs"

st.set_page_config(page_title="OSINT Monitor", page_icon="🛰️", layout="wide")


@st.cache_data(ttl=300)
def load_rows() -> list[dict]:
    conn = db.connect()
    db.init_db(conn)
    rows = [dict(r) for r in db.recent_events(conn, limit=1500)]
    conn.close()
    return rows


@st.cache_data(ttl=300)
def load_signals() -> list[dict]:
    conn = db.connect()
    db.init_db(conn)
    rows = [dict(r) for r in db.recent_signals(conn, limit=25)]
    conn.close()
    return rows


@st.cache_data(ttl=300)
def load_ais() -> list[dict]:
    conn = db.connect()
    db.init_db(conn)
    rows = [dict(r) for r in db.ais_zone_summary(conn)]
    conn.close()
    return rows


def load_brief() -> str | None:
    p = BRIEF_DIR / "latest.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


def within_window(iso: str | None, hours: int) -> bool:
    if not iso:
        return True
    try:
        ts = datetime.fromisoformat(iso)
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts >= datetime.now(timezone.utc) - timedelta(hours=hours)


# --------------------------------------------------------------------------- #
st.title("🛰️ OSINT Monitor")
st.caption("Personal aggregator — GDELT · RSS · prediction markets · AIS. "
           "X stays manual: the signals below tell you where to point your eyes.")

rows = load_rows()
signals = load_signals()

# ---- Signals strip (the point of the tool) ----
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
todays = [s for s in signals if (s["created_at"] or "").startswith(today)]
st.subheader("⚠️ Signals to watch")
if not todays:
    st.caption("No signals fired today. (They appear as markets swing or news "
               "volume spikes — see thresholds in config.yaml.)")
else:
    for s in todays:
        icon = "📊" if s["kind"] == "market_swing" else "📈"
        with st.container(border=True):
            if s["url"]:
                st.markdown(f"{icon} **[{s['title']}]({s['url']})**")
            else:
                st.markdown(f"{icon} **{s['title']}**")
            if s["detail"]:
                st.caption(s["detail"])

st.divider()

if not rows:
    st.info("No events yet. Run `python scripts/run_once.py` to collect some.")
    st.stop()

feed_tab, brief_tab, sea_tab = st.tabs(["📰 Feed", "📝 Daily Brief", "⚓ Maritime"])

# ============================ FEED ============================ #
with feed_tab:
    with st.sidebar:
        st.header("Feed filters")
        window = st.select_slider(
            "Time window (hours)", options=[6, 12, 24, 48, 72, 168], value=24
        )
        all_types = sorted({r["source_type"] for r in rows})
        types = st.multiselect("Source type", all_types, default=all_types)
        all_topics = sorted(
            {t.strip() for r in rows for t in (r["topics"] or "").split(",") if t.strip()}
        )
        topics = st.multiselect("Topic", all_topics, default=[])
        query = st.text_input("Search title").lower().strip()

    filtered = [
        r for r in rows
        if r["source_type"] in types
        and within_window(r["published_at"], window)
        and (not query or query in (r["title"] or "").lower())
        and (not topics or any(t in (r["topics"] or "") for t in topics))
    ]

    c1, c2, c3 = st.columns(3)
    c1.metric("Events in window", len(filtered))
    c2.metric("Sources", len({r["source"] for r in filtered}))
    c3.metric("Markets tracked", len([r for r in filtered if r["source_type"] == "market"]))
    st.divider()

    for r in filtered[:400]:
        ts = (r["published_at"] or r["collected_at"] or "")[:16].replace("T", " ")
        badge = "📊 " if r["source_type"] == "market" else ""
        meta = " · ".join(filter(None, [ts, r["source"], r["region"], r["topics"]]))
        if r["url"]:
            st.markdown(f"{badge}**[{r['title']}]({r['url']})**")
        else:
            st.markdown(f"{badge}**{r['title']}**")
        st.caption(meta)
        if r["summary"]:
            st.caption(r["summary"])
        st.divider()

# ============================ BRIEF ============================ #
with brief_tab:
    brief = load_brief()
    if brief:
        st.markdown(brief)
    else:
        st.info("No brief yet. Run `python scripts/make_brief.py` to generate one. "
                "Set ANTHROPIC_API_KEY for a synthesized brief, or leave it unset "
                "for a free grouped digest.")

# ============================ MARITIME ============================ #
with sea_tab:
    ais = load_ais()
    if not ais:
        st.info("No AIS data yet. It's optional: set AISSTREAM_API_KEY, set "
                "`ais.enabled: true` in config.yaml, then run "
                "`python scripts/collect_ais.py`.")
    else:
        st.caption("Latest vessel snapshot per watched chokepoint. Terrestrial "
                   "AIS — a low count in open water is a coverage gap, not "
                   "necessarily an empty sea.")
        for z in ais:
            last = (z["last_seen"] or "")[:16].replace("T", " ")
            avg = f"{z['avg_speed']:.1f} kn" if z["avg_speed"] is not None else "—"
            col1, col2, col3 = st.columns([2, 1, 1])
            col1.metric(z["zone"], f"{z['vessels']} vessels")
            col2.metric("Avg speed", avg)
            col3.metric("Last seen (UTC)", last or "—")

        with st.expander("Vessel-level detail"):
            conn = db.connect()
            for z in ais:
                st.markdown(f"**{z['zone']}**")
                vs = db.ais_positions_for_zone(conn, z["zone"])
                for v in vs[:50]:
                    nm = v["name"] or v["mmsi"]
                    sog = f"{v['sog']:.1f}kn" if v["sog"] is not None else "?"
                    st.caption(f"{nm} — {sog} @ {v['lat']:.3f},{v['lon']:.3f}")
            conn.close()

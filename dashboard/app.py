"""Streamlit dashboard — your read-only window into everything collected.

Run locally:   streamlit run dashboard/app.py
Deploy free:   push to GitHub, point Streamlit Community Cloud at this file.

Layout: a Signals strip up top (where to look now), then topic tabs
(Maritime / Conflict / Geopolitics / Policy / Other), a dedicated Markets tab
with probability trend charts, and the Daily Brief. Splitting by topic instead
of one big Feed means each tab answers a narrower question at a glance.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from osint import db  # noqa: E402

BRIEF_DIR = Path(__file__).resolve().parent.parent / "data" / "briefs"

st.set_page_config(page_title="OSINT Monitor", page_icon="🛰️", layout="wide")

# Topic tabs mirror the labels normalize.py already assigns to every event
# (see osint/normalize.py::TOPIC_KEYWORDS). Order here = tab order on screen.
TOPIC_TABS = [
    ("maritime", "⚓ Maritime"),
    ("conflict", "💥 Conflict"),
    ("geopolitics", "🌐 Geopolitics"),
    ("policy", "📜 Policy"),
]


@st.cache_data(ttl=300)
def load_rows() -> list[dict]:
    conn = db.connect()
    db.init_db(conn)
    rows = [dict(r) for r in db.recent_events(conn, limit=2000)]
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


@st.cache_data(ttl=300)
def load_market_latest() -> list[dict]:
    conn = db.connect()
    db.init_db(conn)
    rows = [dict(r) for r in db.latest_markets(conn)]
    conn.close()
    return rows


@st.cache_data(ttl=300)
def load_market_series(market_id: str) -> list[dict]:
    conn = db.connect()
    db.init_db(conn)
    rows = [dict(r) for r in db.market_history_series(conn, market_id)]
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


def has_topic(row: dict, topic: str) -> bool:
    tags = {t.strip() for t in (row["topics"] or "").split(",") if t.strip()}
    return topic in tags


def render_event_list(items: list[dict], empty_msg: str) -> None:
    if not items:
        st.caption(empty_msg)
        return
    c1, c2 = st.columns(2)
    c1.metric("Items in window", len(items))
    c2.metric("Sources", len({r["source"] for r in items}))
    st.divider()
    for r in items[:300]:
        ts = (r["published_at"] or r["collected_at"] or "")[:16].replace("T", " ")
        meta = " · ".join(filter(None, [ts, r["source"], r["region"], r["topics"]]))
        if r["url"]:
            st.markdown(f"**[{r['title']}]({r['url']})**")
        else:
            st.markdown(f"**{r['title']}**")
        st.caption(meta)
        if r["summary"]:
            st.caption(r["summary"])
        st.divider()


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

# ---- Global filters (apply to every topic tab; markets & brief have their own) ----
with st.sidebar:
    st.header("Filters")
    window = st.select_slider(
        "Time window (hours)", options=[6, 12, 24, 48, 72, 168], value=24
    )
    all_regions = sorted(
        {t.strip() for r in rows for t in (r["region"] or "").split(",") if t.strip()}
    )
    regions = st.multiselect("Region", all_regions, default=[])
    query = st.text_input("Search title").lower().strip()

news_rows = [r for r in rows if r["source_type"] != "market"]


def apply_filters(items: list[dict]) -> list[dict]:
    return [
        r for r in items
        if within_window(r["published_at"], window)
        and (not query or query in (r["title"] or "").lower())
        and (not regions or any(g in (r["region"] or "") for g in regions))
    ]


filtered_news = apply_filters(news_rows)

tab_labels = [label for _, label in TOPIC_TABS] + ["🗂️ Other", "📊 Markets", "📝 Daily Brief"]
tabs = st.tabs(tab_labels)

# ============================ TOPIC TABS ============================ #
for (topic_key, _), tab in zip(TOPIC_TABS, tabs[: len(TOPIC_TABS)]):
    with tab:
        items = [r for r in filtered_news if has_topic(r, topic_key)]

        if topic_key == "maritime":
            ais = load_ais()
            if ais:
                st.subheader("Vessel picture (AIS)")
                st.caption("Terrestrial AIS — a low count in open water is a "
                           "coverage gap, not necessarily an empty sea.")
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
                st.divider()
                st.subheader("Maritime news")
            else:
                st.caption("No AIS data yet. It's optional: set AISSTREAM_API_KEY, "
                           "set `ais.enabled: true` in config.yaml, then run "
                           "`python scripts/collect_ais.py`.")

        render_event_list(items, "No items tagged for this topic in the current window.")

# ============================ OTHER (untagged news) ============================ #
with tabs[len(TOPIC_TABS)]:
    st.caption("Items GDELT/RSS collected that didn't match any topic keyword "
               "in normalize.py — check here so nothing silently disappears.")
    known = {k for k, _ in TOPIC_TABS}
    items = [r for r in filtered_news if not any(has_topic(r, k) for k in known)]
    render_event_list(items, "Nothing uncategorized in the current window.")

# ============================ MARKETS ============================ #
with tabs[len(TOPIC_TABS) + 1]:
    markets = load_market_latest()
    if not markets:
        st.info("No market data yet. Set `markets.enabled: true` in config.yaml "
                 "and run the collector.")
    else:
        if query:
            markets = [m for m in markets if query in (m["question"] or "").lower()]
        c1, c2 = st.columns(2)
        c1.metric("Markets tracked", len(markets))
        c2.metric("Platforms", len({m["platform"] for m in markets}))
        st.caption("Prediction markets — a sharp probability move often "
                   "precedes the news. Sorted by most recently updated.")
        st.divider()
        for m in markets[:100]:
            pct = round(m["probability"] * 100)
            ts = (m["ts"] or "")[:16].replace("T", " ")
            with st.container(border=True):
                if m["url"]:
                    st.markdown(f"📊 **[{m['question']}]({m['url']})** — {pct}%")
                else:
                    st.markdown(f"📊 **{m['question']}** — {pct}%")
                st.caption(f"{m['platform']} · last updated {ts} UTC")
                series = load_market_series(m["market_id"])
                if len(series) > 1:
                    df = pd.DataFrame(series)
                    df["ts"] = pd.to_datetime(df["ts"])
                    df = df.set_index("ts")[["probability"]]
                    st.line_chart(df, height=150)

# ============================ BRIEF ============================ #
with tabs[len(TOPIC_TABS) + 2]:
    brief = load_brief()
    if brief:
        st.markdown(brief)
    else:
        st.info("No brief yet. Run `python scripts/make_brief.py` to generate one. "
                "Set ANTHROPIC_API_KEY for a synthesized brief, or leave it unset "
                "for a free grouped digest.")

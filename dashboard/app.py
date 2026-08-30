"""Streamlit dashboard — your read-only window into everything collected.

Run locally:   streamlit run dashboard/app.py
Deploy free:   push to GitHub, point Streamlit Community Cloud at this file.

Layout: a Signals strip up top (where to look now), then topic tabs
(Maritime / Conflict / Geopolitics / Policy / Other), a Markets tab with
probability trend charts, a Filings tab (SEC EDGAR), an Aircraft tab (ADS-B),
a Sanctions tab (Commerce/State/Treasury consolidated screening list), a
Starred tab, and the Daily Brief. Within each news tab, near-duplicate
stories from different sources are clustered into one card, and every item
can be starred for later.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from osint import db  # noqa: E402
from osint.normalize import cluster_titles  # noqa: E402

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

SIGNAL_ICONS = {
    "market_swing": "📊",
    "news_spike": "📈",
    "correlated": "🔗",
    "sanctions_listing": "🚫",
}


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
def load_aircraft() -> list[dict]:
    conn = db.connect()
    db.init_db(conn)
    rows = [dict(r) for r in db.aircraft_zone_summary(conn)]
    conn.close()
    return rows


@st.cache_data(ttl=300)
def load_map_points() -> tuple[list[dict], list[dict]]:
    conn = db.connect()
    db.init_db(conn)
    vessels = [dict(r) for r in db.all_ais_positions(conn)]
    aircraft = [dict(r) for r in db.all_aircraft_positions(conn)]
    conn.close()
    return vessels, aircraft


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


def load_starred_ids() -> set[str]:
    # Deliberately uncached (tiny table) so a star/unstar click is reflected
    # immediately on the same rerun instead of waiting out the data cache TTL.
    conn = db.connect()
    db.init_db(conn)
    ids = db.starred_ids(conn)
    conn.close()
    return ids


def toggle_star(event_id: str, currently_starred: bool) -> None:
    conn = db.connect()
    db.init_db(conn)
    if currently_starred:
        db.unstar_event(conn, event_id)
    else:
        db.star_event(conn, event_id)
    conn.close()


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


def render_event_list(items: list[dict], empty_msg: str, key_prefix: str) -> None:
    """Cluster near-duplicate stories, then render one card per cluster with
    a star toggle on the lead item and an expander for the rest."""
    if not items:
        st.caption(empty_msg)
        return

    starred = load_starred_ids()
    clusters = cluster_titles(items)

    c1, c2, c3 = st.columns(3)
    c1.metric("Items in window", len(items))
    c2.metric("Stories (deduped)", len(clusters))
    c3.metric("Sources", len({r["source"] for r in items}))
    st.divider()

    for idx, cluster in enumerate(clusters[:300]):
        primary, *others = cluster
        ts = (primary["published_at"] or primary["collected_at"] or "")[:16].replace("T", " ")
        meta = " · ".join(filter(None, [ts, primary["source"], primary["region"], primary["topics"]]))

        text_col, star_col = st.columns([0.94, 0.06])
        with text_col:
            if primary["url"]:
                st.markdown(f"**[{primary['title']}]({primary['url']})**")
            else:
                st.markdown(f"**{primary['title']}**")
            st.caption(meta)
            if primary["summary"]:
                st.caption(primary["summary"])
            if others:
                label = f"+{len(others)} more source{'s' if len(others) > 1 else ''} on this story"
                with st.expander(label):
                    for o in others:
                        ots = (o["published_at"] or o["collected_at"] or "")[:16].replace("T", " ")
                        if o["url"]:
                            st.markdown(f"- [{o['title']}]({o['url']}) — {o['source']} ({ots})")
                        else:
                            st.markdown(f"- {o['title']} — {o['source']} ({ots})")
        with star_col:
            is_starred = primary["id"] in starred
            key = f"star_{key_prefix}_{idx}_{primary['id']}"
            new_val = st.checkbox("⭐", value=is_starred, key=key, label_visibility="collapsed")
            if new_val != is_starred:
                toggle_star(primary["id"], is_starred)
                st.rerun()
        st.divider()


def render_map(vessels: list[dict], aircraft: list[dict]) -> None:
    points = []
    for v in vessels:
        if v["lat"] is not None and v["lon"] is not None:
            points.append({"lat": v["lat"], "lon": v["lon"],
                            "label": v["name"] or v["mmsi"], "kind": "Vessel",
                            "color": [0, 149, 255]})
    for a in aircraft:
        if a["lat"] is not None and a["lon"] is not None:
            points.append({"lat": a["lat"], "lon": a["lon"],
                            "label": a["callsign"] or a["icao24"], "kind": "Aircraft",
                            "color": [255, 99, 71]})
    if not points:
        st.caption("No positions to plot yet.")
        return
    df = pd.DataFrame(points)
    layer = pdk.Layer(
        "ScatterplotLayer",
        data=df,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=4000,
        pickable=True,
    )
    view_state = pdk.ViewState(
        latitude=float(df["lat"].mean()), longitude=float(df["lon"].mean()), zoom=3,
    )
    st.pydeck_chart(pdk.Deck(
        layers=[layer], initial_view_state=view_state,
        tooltip={"text": "{kind}: {label}"},
    ))
    legend = []
    if vessels:
        legend.append("🔵 Vessels (AIS)")
    if aircraft:
        legend.append("🔴 Aircraft (ADS-B)")
    st.caption("  ·  ".join(legend))


# --------------------------------------------------------------------------- #
st.title("🛰️ OSINT Monitor")
st.caption("Personal aggregator — GDELT · RSS · SEC EDGAR · sanctions lists · "
           "prediction markets · AIS · ADS-B. X stays manual: the signals "
           "below tell you where to point your eyes.")

rows = load_rows()
signals = load_signals()

# ---- Signals strip (the point of the tool) ----
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
todays = [s for s in signals if (s["created_at"] or "").startswith(today)]
st.subheader("⚠️ Signals to watch")
if not todays:
    st.caption("No signals fired today. (They appear as markets swing, news "
               "volume spikes, the two overlap, or a new sanctions listing "
               "shows up — see thresholds in config.yaml.)")
else:
    for s in todays:
        icon = SIGNAL_ICONS.get(s["kind"], "•")
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

# ---- Global filters (apply to every topic tab; markets/filings/brief have their own) ----
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

# Markets, filings, and sanctions listings get their own dedicated tabs; keep
# them out of the topic tabs / Other bucket so nothing shows up twice.
news_rows = [r for r in rows if r["source_type"] not in ("market", "filing", "sanctions")]


def apply_filters(items: list[dict]) -> list[dict]:
    return [
        r for r in items
        if within_window(r["published_at"], window)
        and (not query or query in (r["title"] or "").lower())
        and (not regions or any(g in (r["region"] or "") for g in regions))
    ]


filtered_news = apply_filters(news_rows)

tab_labels = (
    [label for _, label in TOPIC_TABS]
    + ["🗂️ Other", "📊 Markets", "🏛️ Filings", "✈️ Aircraft", "🚫 Sanctions",
       "⭐ Starred", "📝 Daily Brief"]
)
tabs = st.tabs(tab_labels)
(i_other, i_markets, i_filings, i_aircraft, i_sanctions, i_starred, i_brief) = range(
    len(TOPIC_TABS), len(TOPIC_TABS) + 7
)

# ============================ TOPIC TABS ============================ #
for t_idx, (topic_key, _) in enumerate(TOPIC_TABS):
    with tabs[t_idx]:
        items = [r for r in filtered_news if has_topic(r, topic_key)]

        if topic_key == "maritime":
            ais = load_ais()
            if ais:
                vessels, _planes = load_map_points()
                render_map(vessels, [])
                st.divider()

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
            else:
                st.caption("No AIS data yet. It's optional: set AISSTREAM_API_KEY, "
                           "set `ais.enabled: true` in config.yaml, then run "
                           "`python scripts/collect_ais.py`.")
            st.subheader("Maritime news")

        render_event_list(items, "No items tagged for this topic in the current window.",
                           key_prefix=topic_key)

# ============================ OTHER (untagged news) ============================ #
with tabs[i_other]:
    st.caption("Items GDELT/RSS collected that didn't match any topic keyword "
               "in normalize.py — check here so nothing silently disappears.")
    known = {k for k, _ in TOPIC_TABS}
    items = [r for r in filtered_news if not any(has_topic(r, k) for k in known)]
    render_event_list(items, "Nothing uncategorized in the current window.", key_prefix="other")

# ============================ MARKETS ============================ #
with tabs[i_markets]:
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

# ============================ FILINGS ============================ #
with tabs[i_filings]:
    st.caption("SEC EDGAR full-text search matches — configure phrases you "
               "care about under `edgar.keywords` in config.yaml. Free, no key, "
               "but SEC requires a real contact in `edgar.user_agent`.")
    filings = apply_filters([r for r in rows if r["source_type"] == "filing"])
    render_event_list(filings, "No filings matched in the current window.", key_prefix="filings")

# ============================ AIRCRAFT (ADS-B) ============================ #
with tabs[i_aircraft]:
    aircraft_zones = load_aircraft()
    if aircraft_zones:
        _vessels, planes = load_map_points()
        render_map([], planes)
        st.divider()
        st.subheader("Airspace picture (ADS-B)")
        st.caption("OpenSky terrestrial/satellite ADS-B coverage — a low count "
                   "is often a coverage gap (or a GitHub Actions runner getting "
                   "rate-limited by OpenSky), not necessarily empty skies.")
        for z in aircraft_zones:
            last = (z["last_seen"] or "")[:16].replace("T", " ")
            avg = f"{z['avg_velocity']:.0f} m/s" if z["avg_velocity"] is not None else "—"
            col1, col2, col3 = st.columns([2, 1, 1])
            col1.metric(z["zone"], f"{z['aircraft']} aircraft")
            col2.metric("Avg speed", avg)
            col3.metric("Last seen (UTC)", last or "—")
        with st.expander("Aircraft-level detail"):
            conn = db.connect()
            for z in aircraft_zones:
                st.markdown(f"**{z['zone']}**")
                acs = db.aircraft_positions_for_zone(conn, z["zone"])
                for a in acs[:50]:
                    nm = a["callsign"] or a["icao24"]
                    v = f"{a['velocity']:.0f}m/s" if a["velocity"] is not None else "?"
                    st.caption(f"{nm} — {v} @ {a['lat']:.3f},{a['lon']:.3f}")
            conn.close()
    else:
        st.caption("No ADS-B data yet. It's optional: set `adsb.enabled: true` "
                   "and zones in config.yaml, then run `python scripts/collect_adsb.py` "
                   "(a free OpenSky account raises the rate limit, but cloud/datacenter "
                   "IPs — including GitHub Actions runners — are still often blocked; "
                   "see the script's docstring).")

# ============================ SANCTIONS ============================ #
with tabs[i_sanctions]:
    st.caption("New additions to the Commerce/State/Treasury consolidated "
               "screening list (OFAC SDN, BIS Entity List, State Dept debarred "
               "list, etc). Diff-only: only entities not seen in a prior run "
               "show up here, so the first run after enabling won't show "
               "anything — that run just seeds the baseline silently.")
    sanctions_items = apply_filters([r for r in rows if r["source_type"] == "sanctions"])
    render_event_list(sanctions_items, "No new sanctions listings in the current window.",
                       key_prefix="sanctions")

# ============================ STARRED ============================ #
with tabs[i_starred]:
    st.caption("Everything you've bookmarked, across every tab.")
    starred_ids = load_starred_ids()
    starred_items = [r for r in rows if r["id"] in starred_ids]
    render_event_list(starred_items, "Nothing starred yet — click ⭐ next to any item.",
                       key_prefix="starred")

# ============================ BRIEF ============================ #
with tabs[i_brief]:
    brief = load_brief()
    if brief:
        st.markdown(brief)
    else:
        st.info("No brief yet. Run `python scripts/make_brief.py` to generate one. "
                "Set ANTHROPIC_API_KEY for a synthesized brief, or leave it unset "
                "for a free grouped digest.")

# 🛰️ OSINT Monitor

A personal, near-zero-cost intelligence aggregator for one operator. It pulls
open sources into one schema, stores them in SQLite, detects cross-source
**signals**, writes a once-a-day **brief**, and shows everything in a Streamlit
dashboard — all runnable free on **GitHub Actions** + **Streamlit Cloud**.

> **X is intentionally not automated.** Automated X scraping is noisy and now
> expensive. This tool does the triage and tells you *where to look*; you open X
> and bring the human read on whatever the signals surface. That division of
> labour is the whole design.

## What it does

| Source | Cost | Notes |
|---|---|---|
| **GDELT** DOC 2.0 | free, no key | global news backbone |
| **RSS / Atom** | free | international press + government releases |
| **Prediction markets** | free, no key | Polymarket + Manifold (Kalshi/Metaculus are extension points) |
| **AIS** (AISStream.io) | free key | optional; live vessel positions at chokepoints |
| **LLM brief** | ~cents/day | optional; one call/day; free digest fallback if no key |

Everything except the optional daily LLM call is **$0**. Well inside sub-$50.

## Architecture (4 thin layers)

```
osint/
  models.py        # the common Event schema + dedup id
  db.py            # SQLite: events, market_history, signals, ais_positions
  normalize.py     # coarse free keyword tagging (region/topic)
  collect.py       # orchestrator: sources -> store -> record markets -> signals
  signals.py       # market swings + news spikes  <- the edge
  brief.py         # once-a-day synthesis (1 LLM call) + free digest fallback
  sources/
    base.py        # Source interface
    rss.py         # RSS / Atom
    gdelt.py       # GDELT DOC 2.0
    markets.py     # Polymarket + Manifold (pure, testable parsers)
dashboard/app.py   # Streamlit UI: Signals strip · Feed · Brief · Maritime
scripts/
  run_once.py      # frequent collector (no LLM, free)  -> every 30 min
  make_brief.py    # daily brief (one LLM call)          -> once a day
  collect_ais.py   # optional bounded AIS stream collector
config.yaml        # feeds, queries, market keywords, thresholds — edit THIS
.github/workflows/ # collect.yml (30m) · brief.yml (daily) · ais.yml (optional)
```

The flow: **collect → normalize → store → detect signals → (daily) synthesize
→ display.** New sources are just new files in `sources/` returning `Event`s.

## Run it locally (5 minutes)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # optional: add keys for the LLM brief / AIS

python scripts/run_once.py      # collect once -> data/osint.db
python scripts/make_brief.py    # (optional) build a brief
streamlit run dashboard/app.py  # open the dashboard
```

First run creates `data/osint.db`. Re-run the collector anytime; duplicates are
ignored automatically. No keys? Everything still works — the brief just uses the
free grouped digest.

## Deploy free

1. Push this folder to a new GitHub repo.
2. Repo → Settings → Actions → General → **Read and write permissions** (lets
   the jobs commit the updated DB back).
3. **Collection:** `collect.yml` runs every 30 min (GDELT + RSS + markets +
   signals) and commits `data/osint.db`.
4. **Brief:** `brief.yml` runs daily. Add repo secret **`ANTHROPIC_API_KEY`**
   (Settings → Secrets → Actions) for a synthesized brief; without it you get
   the free digest.
5. **Dashboard:** create a free app at share.streamlit.io pointing at
   `dashboard/app.py`. It reads the committed DB + latest brief.

> The DB is committed to the repo so the free Actions writer and the free
> Streamlit reader can share it — the pragmatic glue for a solo setup. If the
> repo ever gets heavy, move storage to a free Postgres tier (Supabase/Neon);
> only `db.py` changes.

## Signals — the point of the tool

Two cheap detectors run every collection (no LLM):

- **market_swing** — a tracked market's probability moved ≥ threshold (default
  10 points) over a window (default 24h). A sharp move often *precedes* the news.
- **news_spike** — a topic's event volume jumped ≥ ratio (default 2.5×) vs the
  prior window and cleared a floor. Something is developing on that theme.

Signals appear at the top of the dashboard and in the brief's "Check manually on
X" section — your cue to go get the human read. Tune all thresholds in
`config.yaml` under `signals:`.

## Maritime (AIS) — optional

1. Free key at https://aisstream.io → put it in `.env` (and as a repo secret for
   `ais.yml`).
2. Set `ais.enabled: true` in `config.yaml`; edit the chokepoint bounding boxes.
3. `python scripts/collect_ais.py` (bounded run) or let `ais.yml` snapshot on a
   schedule.

**Read this caveat:** AISStream is terrestrial AIS. Coverage in open ocean is
patchy, so a low vessel count mid-strait is a **coverage gap, not an empty sea.**
Never read absence as an event.

## Make it yours

- Edit `config.yaml`: add the RSS + government feeds you actually track, tune the
  GDELT queries, and set the market `keywords` to your regions/topics.
- Starter feeds are examples — **verify each URL resolves.**
- Add Kalshi/Metaculus by writing a parser alongside `markets.py` (Kalshi needs
  RSA-key auth; Metaculus exposes community forecasts via its API).

## Cost control

- The frequent collector makes **zero** LLM calls — it's free forever.
- The brief is **one** call per day. Default model is Haiku (~a fraction of a
  cent/day). Bump to `claude-sonnet-4-6` in `config.yaml` for richer synthesis.
- No paid data sources. X is manual on purpose.

## Ethics & accuracy

Respect each source's ToS and rate limits, attribute everything, and don't
redistribute raw scraped data. Be skeptical of single-source claims — the brief
is told to flag them. And mind the AIS caveat above.

## Verified

The data logic (storage, dedup, tagging, RSS parsing, market parsers, both
signal detectors, the brief fallback, and AIS parsing/storage) ships with a
smoke test that passes end-to-end without any network access. Live API calls
run on your machine / in Actions, which have open internet.

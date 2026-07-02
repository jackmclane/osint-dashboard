"""Generate the daily brief. Run once a day (separate workflow) so the frequent
collector stays free and LLM spend is exactly one call per day.

    python scripts/make_brief.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from osint import db  # noqa: E402
from osint.brief import generate  # noqa: E402
from osint.collect import load_config  # noqa: E402

if __name__ == "__main__":
    conn = db.connect()
    db.init_db(conn)
    path, _ = generate(conn, load_config())
    conn.close()
    print(f"brief -> {path}")
    sys.exit(0)

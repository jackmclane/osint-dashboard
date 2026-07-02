"""Entry point. Run locally or from GitHub Actions:

    python scripts/run_once.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from osint.collect import run  # noqa: E402

if __name__ == "__main__":
    new = run()
    # non-zero-ish signal is fine; Actions just needs a clean exit
    sys.exit(0)

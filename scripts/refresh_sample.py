"""Génère data/sample_prices.csv (snapshot de secours si Yahoo Finance est indisponible).

Usage (en local, depuis la racine du projet) :
    python scripts/refresh_sample.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import UNIVERSE  # noqa: E402
from src.data import SAMPLE_PATH, fetch_prices  # noqa: E402

if __name__ == "__main__":
    end = date.today()
    prices = fetch_prices([a.ticker for a in UNIVERSE], end - timedelta(days=3 * 365 + 10), end)
    SAMPLE_PATH.parent.mkdir(exist_ok=True)
    prices.round(4).to_csv(SAMPLE_PATH)
    print(f"{len(prices)} séances enregistrées dans {SAMPLE_PATH}")

"""Récupération des prix via yfinance (données publiques Yahoo Finance)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_prices.csv"


class DataError(RuntimeError):
    """Erreur de récupération ou de qualité des données."""


def _extract_close(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise DataError("Aucune donnée renvoyée par Yahoo Finance.")
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:  # un seul ticker
        prices = raw[["Close"]].rename(columns={"Close": tickers[0]})
    return prices


def clean_prices(prices: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Aligne les séries, comble les jours fériés locaux et valide la couverture."""
    missing = [t for t in tickers if t not in prices.columns or prices[t].dropna().empty]
    if missing:
        raise DataError(f"Pas de données pour : {', '.join(missing)}")
    prices = prices[tickers].sort_index()
    prices.index = pd.to_datetime(prices.index).tz_localize(None)
    # Forward-fill uniquement (pas de look-ahead), puis on démarre à la 1re date commune.
    prices = prices.ffill().dropna()
    if len(prices) < 20:
        raise DataError("Historique trop court (< 20 séances) pour calculer des métriques fiables.")
    return prices


def fetch_prices(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """Télécharge les cours de clôture ajustés (dividendes/splits)."""
    try:
        raw = yf.download(
            tickers,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:  # yfinance lève des exceptions hétérogènes
        raise DataError(f"Échec du téléchargement Yahoo Finance : {exc}") from exc
    return clean_prices(_extract_close(raw, tickers), tickers)


def load_sample_prices(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """Repli hors-ligne : snapshot CSV généré par scripts/refresh_sample.py."""
    if not SAMPLE_PATH.exists():
        raise DataError("Aucun jeu de données de secours disponible (data/sample_prices.csv).")
    prices = pd.read_csv(SAMPLE_PATH, index_col=0, parse_dates=True)
    prices = prices.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    return clean_prices(prices, tickers)

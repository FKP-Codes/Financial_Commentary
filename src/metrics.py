"""Calculs de performance et de risque (fonctions pures, testées)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import TRADING_DAYS


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("La somme des poids doit être strictement positive.")
    return {k: v / total for k, v in weights.items()}


def portfolio_value(prices: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Valeur base 100 d'un portefeuille buy-and-hold (poids initiaux, sans rebalancement)."""
    w = pd.Series(normalize_weights(weights)).reindex(prices.columns).fillna(0.0)
    rebased = prices / prices.iloc[0]
    return (rebased * w).sum(axis=1) * 100


def total_return(series: pd.Series) -> float:
    return float(series.iloc[-1] / series.iloc[0] - 1)


def annualized_return(series: pd.Series) -> float:
    n_days = len(series) - 1
    if n_days <= 0:
        return 0.0
    return float((1 + total_return(series)) ** (TRADING_DAYS / n_days) - 1)


def annualized_volatility(series: pd.Series) -> float:
    returns = series.pct_change().dropna()
    return float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS))


def drawdown_series(series: pd.Series) -> pd.Series:
    return series / series.cummax() - 1


def max_drawdown(series: pd.Series) -> float:
    return float(drawdown_series(series).min())


def sharpe_ratio(series: pd.Series, risk_free: float) -> float:
    """Sharpe annualisé calculé sur rendements journaliers en excès du taux sans risque."""
    returns = series.pct_change().dropna()
    daily_rf = (1 + risk_free) ** (1 / TRADING_DAYS) - 1
    excess = returns - daily_rf
    std = excess.std(ddof=1)
    if np.isnan(std) or std < 1e-12:
        return float("nan")
    return float(excess.mean() / std * np.sqrt(TRADING_DAYS))


def tracking_error(portfolio: pd.Series, benchmark: pd.Series) -> float:
    active = portfolio.pct_change().dropna() - benchmark.pct_change().dropna()
    return float(active.std(ddof=1) * np.sqrt(TRADING_DAYS))


def summary_metrics(series: pd.Series, risk_free: float) -> dict[str, float]:
    return {
        "Performance cumulée": total_return(series),
        "Performance annualisée": annualized_return(series),
        "Volatilité annualisée": annualized_volatility(series),
        "Drawdown maximum": max_drawdown(series),
        "Ratio de Sharpe": sharpe_ratio(series, risk_free),
    }


def contributions(prices: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Contribution de chaque ligne à la performance (exacte en buy-and-hold)."""
    w = pd.Series(normalize_weights(weights)).reindex(prices.columns).fillna(0.0)
    asset_returns = prices.iloc[-1] / prices.iloc[0] - 1
    return w * asset_returns


def monthly_returns(series: pd.Series) -> pd.Series:
    month_end = series.resample("ME").last()
    # Premier mois : rendement depuis le début de la période, pas depuis zéro.
    month_end = pd.concat([series.iloc[:1], month_end])
    return month_end.pct_change().dropna()


def current_weights(prices: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Poids en fin de période après dérive des marchés (buy-and-hold)."""
    w = pd.Series(normalize_weights(weights)).reindex(prices.columns).fillna(0.0)
    drifted = w * prices.iloc[-1] / prices.iloc[0]
    return drifted / drifted.sum()

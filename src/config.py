"""Configuration centrale : univers d'investissement, allocations et paramètres."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    ticker: str  # Ticker Yahoo Finance
    name: str  # Nom affiché
    asset_class: str  # Classe d'actifs (utilisée dans le commentaire)


# Trois ETF UCITS cotés en EUR sur Xetra : pas de conversion de change nécessaire.
UNIVERSE: list[Asset] = [
    Asset("SXR8.DE", "iShares Core S&P 500 UCITS ETF", "Actions US"),
    Asset("EXW1.DE", "iShares Core EURO STOXX 50 UCITS ETF", "Actions zone euro"),
    Asset("EUNH.DE", "iShares Core Euro Government Bond UCITS ETF", "Obligations souveraines zone euro"),
]

# Allocation du portefeuille fictif vs allocation stratégique (benchmark composite).
DEFAULT_PORTFOLIO_WEIGHTS: dict[str, float] = {"SXR8.DE": 0.50, "EXW1.DE": 0.20, "EUNH.DE": 0.30}
DEFAULT_BENCHMARK_WEIGHTS: dict[str, float] = {"SXR8.DE": 0.40, "EXW1.DE": 0.20, "EUNH.DE": 0.40}

TRADING_DAYS = 252
DEFAULT_RISK_FREE_RATE = 0.02  # Taux sans risque annuel (proxy €STR), modifiable dans l'app

# Modèle Claude : surchargeable via la variable d'environnement / secret CLAUDE_MODEL.
DEFAULT_MODEL = "claude-haiku-4-5"
MAX_GENERATIONS_PER_SESSION = 5  # Garde-fou coût sur la démo publique

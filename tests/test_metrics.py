import numpy as np
import pandas as pd
import pytest

from src import metrics as m
from src.commentary import build_context, build_user_prompt


@pytest.fixture
def prices() -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=253)
    return pd.DataFrame(
        {
            "A": np.linspace(100, 120, 253),  # +20 %
            "B": np.linspace(50, 45, 253),  # -10 %
        },
        index=idx,
    )


def test_portfolio_value_buy_and_hold(prices):
    port = m.portfolio_value(prices, {"A": 0.5, "B": 0.5})
    assert port.iloc[0] == pytest.approx(100)
    assert m.total_return(port) == pytest.approx(0.05)  # 0.5*20% + 0.5*(-10%)


def test_weights_are_normalized(prices):
    a = m.portfolio_value(prices, {"A": 1, "B": 1})
    b = m.portfolio_value(prices, {"A": 0.5, "B": 0.5})
    pd.testing.assert_series_equal(a, b)


def test_contributions_sum_to_total_return(prices):
    w = {"A": 0.7, "B": 0.3}
    assert m.contributions(prices, w).sum() == pytest.approx(m.total_return(m.portfolio_value(prices, w)))


def test_annualized_return_one_year(prices):
    # 253 points = 252 rendements journaliers = 1 an
    assert m.annualized_return(prices["A"]) == pytest.approx(0.20)


def test_max_drawdown():
    s = pd.Series([100, 120, 90, 110, 130], index=pd.bdate_range("2024-01-01", periods=5))
    assert m.max_drawdown(s) == pytest.approx(90 / 120 - 1)


def test_volatility_zero_for_constant_growth():
    s = pd.Series(100 * 1.001 ** np.arange(100), index=pd.bdate_range("2024-01-01", periods=100))
    assert m.annualized_volatility(s) == pytest.approx(0, abs=1e-12)
    assert np.isnan(m.sharpe_ratio(s, 0.02))


def test_sharpe_sign():
    rng = np.random.default_rng(0)
    s = pd.Series(100 * np.cumprod(1 + rng.normal(0.001, 0.01, 500)), index=pd.bdate_range("2024-01-01", periods=500))
    assert m.sharpe_ratio(s, 0.0) > 0


def test_monthly_returns_compound_to_total(prices):
    port = m.portfolio_value(prices, {"A": 0.6, "B": 0.4})
    monthly = m.monthly_returns(port)
    assert (1 + monthly).prod() - 1 == pytest.approx(m.total_return(port))


def test_current_weights_sum_to_one(prices):
    w = m.current_weights(prices, {"A": 0.5, "B": 0.5})
    assert w.sum() == pytest.approx(1)
    assert w["A"] > 0.5  # l'actif gagnant a vu son poids dériver à la hausse


def test_prompt_contains_data_and_guardrails(prices):
    port = m.portfolio_value(prices, {"A": 0.6, "B": 0.4})
    bench = m.portfolio_value(prices, {"A": 0.5, "B": 0.5})
    ctx = build_context(
        period_start="2024-01-01",
        period_end="2024-12-31",
        portfolio_metrics=m.summary_metrics(port, 0.02),
        benchmark_metrics=m.summary_metrics(bench, 0.02),
        tracking_error=m.tracking_error(port, bench),
        assets=[],
        monthly={},
    )
    assert ctx["surperformance_relative_pts"] == pytest.approx(3.0, abs=0.01)
    prompt = build_user_prompt(ctx, "Investisseurs institutionnels", "Court", "")
    assert "<donnees_portefeuille>" in prompt
    assert "ne pas attribuer de causes externes" in prompt

"""Générateur de commentaires de gestion IA — application Streamlit."""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from src import metrics as m
from src.commentary import AUDIENCE_GUIDE, LENGTH_GUIDE, build_context, build_user_prompt, stream_commentary
from src.config import (
    DEFAULT_BENCHMARK_WEIGHTS,
    DEFAULT_MODEL,
    DEFAULT_PORTFOLIO_WEIGHTS,
    DEFAULT_RISK_FREE_RATE,
    MAX_GENERATIONS_PER_SESSION,
    UNIVERSE,
)
from src.data import DataError, fetch_prices, load_sample_prices

load_dotenv()
st.set_page_config(page_title="Commentaire de gestion IA", page_icon="📈", layout="wide")

NAMES = {a.ticker: a.name for a in UNIVERSE}
CLASSES = {a.ticker: a.asset_class for a in UNIVERSE}
TICKERS = [a.ticker for a in UNIVERSE]
PORTFOLIO_COLOR, BENCHMARK_COLOR = "#1f4e79", "#9aa5b1"
ASSET_COLORS = {"SXR8.DE": "#d68910", "EXW1.DE": "#7d3c98", "EUNH.DE": "#17a589"}


def get_secret(name: str, default: str = "") -> str:
    """Lit st.secrets (Streamlit Cloud) puis les variables d'environnement (.env en local)."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # pas de secrets.toml en local
        pass
    return os.getenv(name, default)


def fmt_pct(x: float) -> str:
    return f"{x:+.2%}".replace(".", ",")


@st.cache_data(ttl=3600, show_spinner="Téléchargement des cours Yahoo Finance…")
def load_prices(tickers: tuple[str, ...], start: date, end: date) -> tuple[pd.DataFrame, bool]:
    """Renvoie (prix, is_sample). Bascule sur le snapshot CSV si Yahoo est indisponible."""
    try:
        return fetch_prices(list(tickers), start, end), False
    except DataError:
        return load_sample_prices(list(tickers), start, end), True


# ----------------------------------------------------------------------------- Sidebar
with st.sidebar:
    st.header("Paramètres")

    preset = st.selectbox("Période", ["Depuis le début de l'année", "1 an", "3 ans", "Personnalisée"], index=1)
    today = date.today()
    if preset == "Depuis le début de l'année":
        start, end = date(today.year - (1 if today.month == 1 and today.day < 15 else 0), 1, 1), today
    elif preset == "1 an":
        start, end = today - timedelta(days=365), today
    elif preset == "3 ans":
        start, end = today - timedelta(days=3 * 365), today
    else:
        start = st.date_input("Début", today - timedelta(days=365), max_value=today - timedelta(days=30))
        end = st.date_input("Fin", today, min_value=start + timedelta(days=30), max_value=today)

    st.subheader("Allocation du portefeuille")
    port_w = {
        t: st.slider(CLASSES[t], 0, 100, int(DEFAULT_PORTFOLIO_WEIGHTS[t] * 100), 5, key=f"p_{t}") / 100
        for t in TICKERS
    }
    st.subheader("Allocation stratégique (benchmark)")
    bench_w = {
        t: st.slider(CLASSES[t], 0, 100, int(DEFAULT_BENCHMARK_WEIGHTS[t] * 100), 5, key=f"b_{t}") / 100
        for t in TICKERS
    }
    for label, w in (("portefeuille", port_w), ("benchmark", bench_w)):
        if abs(sum(w.values()) - 1) > 1e-9:
            st.caption(f"Poids {label} = {sum(w.values()):.0%} → renormalisés à 100 %.")

    rf = st.number_input("Taux sans risque annuel (%)", 0.0, 10.0, DEFAULT_RISK_FREE_RATE * 100, 0.25) / 100

    st.subheader("Commentaire")
    audience = st.selectbox("Public cible", list(AUDIENCE_GUIDE))
    length = st.select_slider("Longueur", list(LENGTH_GUIDE), value="Standard")

    owner_key = get_secret("ANTHROPIC_API_KEY")
    user_key = st.text_input(
        "Votre clé API Anthropic (optionnel)",
        type="password",
        help="Laissez vide pour utiliser la clé de démonstration (générations limitées par session).",
    )

if sum(port_w.values()) == 0 or sum(bench_w.values()) == 0:
    st.error("Chaque allocation doit contenir au moins une ligne avec un poids non nul.")
    st.stop()

# ----------------------------------------------------------------------------- Données
st.title("📈 Générateur de commentaires de gestion IA")
st.caption(
    "Portefeuille fictif de 3 ETF UCITS · données publiques Yahoo Finance · commentaire rédigé par Claude "
    "à partir des seuls chiffres affichés."
)

try:
    prices, is_sample = load_prices(tuple(TICKERS), start, end)
except DataError as exc:
    st.error(f"Impossible de charger les données : {exc}")
    st.stop()
if is_sample:
    st.warning("Yahoo Finance est indisponible : affichage d'un snapshot de données publiques enregistré.")

port = m.portfolio_value(prices, port_w)
bench = m.portfolio_value(prices, bench_w)
port_metrics = m.summary_metrics(port, rf)
bench_metrics = m.summary_metrics(bench, rf)
te = m.tracking_error(port, bench)
period_label = f"{prices.index[0]:%d/%m/%Y} → {prices.index[-1]:%d/%m/%Y}"

# ----------------------------------------------------------------------------- KPIs
st.subheader(f"Performance · {period_label}")
cols = st.columns(5)
for col, (label, value) in zip(cols, port_metrics.items(), strict=True):
    delta = value - bench_metrics[label]
    if label == "Ratio de Sharpe":
        col.metric(label, f"{value:.2f}".replace(".", ","), f"{delta:+.2f} vs bench".replace(".", ","))
    else:
        inverse = label in ("Volatilité annualisée",)
        col.metric(
            label,
            f"{value:.2%}".replace(".", ","),
            f"{delta * 100:+.2f} pts vs bench".replace(".", ","),
            delta_color="inverse" if inverse else "normal",
        )

# ----------------------------------------------------------------------------- Graphiques
tab_perf, tab_dd, tab_contrib = st.tabs(["Évolution base 100", "Drawdown", "Contributions"])

with tab_perf:
    fig = go.Figure()
    fig.add_scatter(x=port.index, y=port, name="Portefeuille", line=dict(color=PORTFOLIO_COLOR, width=3))
    fig.add_scatter(
        x=bench.index,
        y=bench,
        name="Allocation stratégique",
        line=dict(color=BENCHMARK_COLOR, width=2, dash="dash"),
    )
    for t in TICKERS:
        s = prices[t] / prices[t].iloc[0] * 100
        fig.add_scatter(x=s.index, y=s, name=CLASSES[t], line=dict(width=1, color=ASSET_COLORS.get(t)), opacity=0.6)
    fig.update_layout(
        height=420,
        hovermode="x unified",
        yaxis_title="Base 100",
        margin=dict(t=10, b=10),
        legend=dict(orientation="h", y=-0.15),
    )
    st.plotly_chart(fig, width="stretch")

with tab_dd:
    fig = go.Figure()
    for s, name, color in ((port, "Portefeuille", PORTFOLIO_COLOR), (bench, "Allocation stratégique", BENCHMARK_COLOR)):
        dd = m.drawdown_series(s) * 100
        fig.add_scatter(x=dd.index, y=dd, name=name, fill="tozeroy", line=dict(color=color))
    fig.update_layout(
        height=380,
        hovermode="x unified",
        yaxis_title="Drawdown (%)",
        margin=dict(t=10, b=10),
        legend=dict(orientation="h", y=-0.15),
    )
    st.plotly_chart(fig, width="stretch")

contrib = m.contributions(prices, port_w)
with tab_contrib:
    fig = go.Figure(
        go.Bar(
            x=[CLASSES[t] for t in contrib.index],
            y=contrib * 100,
            marker_color=[PORTFOLIO_COLOR if v >= 0 else "#c0392b" for v in contrib],
            text=[fmt_pct(v) for v in contrib],
            textposition="outside",
        )
    )
    fig.update_layout(height=380, yaxis_title="Contribution (pts de %)", margin=dict(t=10, b=10))
    st.plotly_chart(fig, width="stretch")

# ----------------------------------------------------------------------------- Tableau détaillé
drift = m.current_weights(prices, port_w)
norm_p, norm_b = m.normalize_weights(port_w), m.normalize_weights(bench_w)
rows = []
for t in TICKERS:
    s = prices[t]
    rows.append(
        {
            "Ligne": NAMES[t],
            "Classe d'actifs": CLASSES[t],
            "Poids initial": norm_p[t],
            "Poids actuel": drift[t],
            "Poids benchmark": norm_b[t],
            "Performance": m.total_return(s),
            "Volatilité": m.annualized_volatility(s),
            "Drawdown max": m.max_drawdown(s),
            "Contribution": contrib[t],
        }
    )
table = pd.DataFrame(rows)
st.subheader("Détail par ligne")
st.dataframe(
    table.style.format({c: "{:.2%}" for c in table.columns if c not in ("Ligne", "Classe d'actifs")}),
    hide_index=True,
    width="stretch",
)

monthly = m.monthly_returns(port)

# ----------------------------------------------------------------------------- Commentaire IA
st.divider()
st.subheader("✍️ Commentaire de gestion")
notes = st.text_area(
    "Contexte de marché du gérant (optionnel)",
    placeholder="Ex. : Baisse des taux de la BCE en juin, rotation sectorielle vers les valeurs cycliques, "
    "prises de profits sur les actions US en fin de période…",
    help="Le modèle n'invente aucun événement : ajoutez ici le contexte macro que vous souhaitez voir cité.",
)

api_key = user_key or owner_key
using_demo_key = not user_key
st.session_state.setdefault("generations", 0)
remaining = MAX_GENERATIONS_PER_SESSION - st.session_state.generations

if not api_key:
    st.info("Ajoutez une clé API Anthropic dans la barre latérale (ou dans `.env` / les secrets Streamlit).")
elif st.button("Générer le commentaire de gestion", type="primary", disabled=using_demo_key and remaining <= 0):
    context = build_context(
        period_start=f"{prices.index[0]:%Y-%m-%d}",
        period_end=f"{prices.index[-1]:%Y-%m-%d}",
        portfolio_metrics=port_metrics,
        benchmark_metrics=bench_metrics,
        tracking_error=te,
        assets=[
            {
                "nom": r["Ligne"],
                "classe_actifs": r["Classe d'actifs"],
                **{
                    k: round(r[k] * 100, 2)
                    for k in (
                        "Poids initial",
                        "Poids actuel",
                        "Poids benchmark",
                        "Performance",
                        "Volatilité",
                        "Drawdown max",
                        "Contribution",
                    )
                },
            }
            for r in rows
        ],
        monthly={f"{d:%Y-%m}": v for d, v in monthly.items()},
    )
    prompt = build_user_prompt(context, audience, length, notes)
    try:
        with st.container(border=True):
            text = st.write_stream(stream_commentary(api_key, get_secret("CLAUDE_MODEL", DEFAULT_MODEL), prompt))
        st.session_state.commentary = text
        if using_demo_key:
            st.session_state.generations += 1
    except Exception as exc:
        st.error(f"Erreur lors de l'appel à l'API Claude : {exc}")
    with st.expander("Voir les données transmises au modèle"):
        st.json(context)
elif st.session_state.get("commentary"):
    with st.container(border=True):
        st.markdown(st.session_state.commentary)

if using_demo_key and api_key:
    st.caption(f"Clé de démonstration : {max(remaining, 0)} génération(s) restante(s) pour cette session.")

if st.session_state.get("commentary"):
    st.download_button(
        "Télécharger (.md)",
        f"# Commentaire de gestion — {period_label}\n\n{st.session_state.commentary}\n",
        file_name=f"commentaire_gestion_{prices.index[-1]:%Y%m%d}.md",
        mime="text/markdown",
    )

st.caption(
    "⚠️ Projet de démonstration. Portefeuille fictif, données publiques Yahoo Finance susceptibles d'erreurs. "
    "Ne constitue pas un conseil en investissement. Les performances passées ne préjugent pas des performances futures."
)

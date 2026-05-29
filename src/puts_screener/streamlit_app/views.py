"""Vistas de la app Streamlit: sidebar, lista, detalle (spec 09 tanda 3).

Capa de presentación. Todas las funciones tocan `streamlit` directamente. La
lógica pura (carga de datos, filtros, construcción del chart) vive en otros
módulos del paquete. Los helpers `_cached_*` decorados con `@st.cache_data`
encapsulan las llamadas a la DB con TTL.
"""

from datetime import date

import pandas as pd
import streamlit as st

from puts_screener.config_streamlit import (
    STREAMLIT_CHART_MONTH_OPTIONS,
    STREAMLIT_DB_QUERY_CACHE_TTL_SECONDS,
    STREAMLIT_DEFAULT_CHART_MONTHS,
    STREAMLIT_PAGE_TITLE,
    STREAMLIT_SIDEBAR_RUN_LIMIT,
)
from puts_screener.formatting import format_price
from puts_screener.streamlit_app.chart import build_chart_payload, build_plotly_figure
from puts_screener.streamlit_app.data_loader import (
    list_recent_runs,
    load_candidate_detail,
    load_run_candidates,
)
from puts_screener.streamlit_app.filters import FilterState
from puts_screener.streamlit_app.models import CandidateDetail, CandidateRow, RunSummary

# --- Cached loaders (TTL=300s) ---


@st.cache_data(ttl=STREAMLIT_DB_QUERY_CACHE_TTL_SECONDS)
def _cached_list_runs() -> list[RunSummary]:
    return list_recent_runs(limit=STREAMLIT_SIDEBAR_RUN_LIMIT)


@st.cache_data(ttl=STREAMLIT_DB_QUERY_CACHE_TTL_SECONDS)
def _cached_run_candidates(run_id: str) -> list[CandidateRow]:
    return load_run_candidates(run_id)


@st.cache_data(ttl=STREAMLIT_DB_QUERY_CACHE_TTL_SECONDS)
def _cached_candidate_detail(run_id: str, ticker: str) -> CandidateDetail:
    return load_candidate_detail(run_id, ticker)


# --- Sidebar ---


def render_sidebar_run_selector() -> str:
    """Sidebar: título + selector de run. Devuelve el run_id seleccionado."""
    st.sidebar.title(STREAMLIT_PAGE_TITLE)
    runs = _cached_list_runs()
    if not runs:
        st.sidebar.error("No hay runs en la base de datos.")
        st.stop()
    selected = st.sidebar.selectbox(
        "Run",
        options=runs,
        format_func=lambda r: r.display_label,
        index=0,
    )
    return selected.run_id


def _tri_state(label: str) -> bool | None:
    """Selectbox tri-estado: indistinto / sí / no. Devuelve None / True / False."""
    choice = st.sidebar.selectbox(label, options=["Indistinto", "Sí", "No"], key=label)
    return {"Indistinto": None, "Sí": True, "No": False}[choice]


_REGIME_OPTIONS = ("uptrend", "lateral", "downtrend", "reversal")
_PRIMARY_TRIGGER_OPTIONS = (
    "pullback_in_uptrend",
    "double_bottom_confirmed",
    "double_bottom_unconfirmed",
    "capitulation_reclaim",
    "hma_weekly_flip",
    "range_floor",
    "post_earnings_dip",
)


def render_sidebar_filters(rows: list[CandidateRow]) -> FilterState:
    """Sidebar: filtros derivados de los rows del run actual. Devuelve FilterState.

    spec 10: el filtro por tier (T1-T5) fue reemplazado por régimen + primary_trigger.
    Runs históricos (pre-spec-10) tienen regime/primary_trigger=None; filtrarlos por
    estos campos los excluye, lo cual es el comportamiento esperado.
    """
    st.sidebar.divider()
    st.sidebar.subheader("Filtros")
    regime = st.sidebar.multiselect("Régimen", options=list(_REGIME_OPTIONS))
    primary_trigger = st.sidebar.multiselect(
        "Trigger primario", options=list(_PRIMARY_TRIGGER_OPTIONS)
    )
    sectors_available = sorted({r.sector for r in rows if r.sector})
    sector = st.sidebar.multiselect("Sector", options=sectors_available)
    score_min = st.sidebar.slider("Score mínimo", 0.0, 25.0, 0.0, step=0.5)
    wheel_only = st.sidebar.checkbox("Solo wheel candidates", value=False)
    requires_earnings = _tri_state("Earnings en 45d")
    requires_ex_div = _tri_state("Ex-div en 45d")
    requires_macro = _tri_state("Evento macro en 45d")
    return FilterState(
        regime=frozenset(regime),
        primary_trigger=frozenset(primary_trigger),
        sector=frozenset(sector),
        score_min=score_min,
        requires_earnings_in_45d=requires_earnings,
        requires_ex_div_in_45d=requires_ex_div,
        requires_macro_in_45d=requires_macro,
        wheel_only=wheel_only,
    )


# --- Tabla principal ---


def _stars(tier: int | None) -> str:
    if tier is None:
        return "—"
    return "⭐" * tier


def _fmt_mcap(value: float | None) -> str:
    """Formato 1.2B / 850M / 12K. 'N/A' si None."""
    if value is None:
        return "N/A"
    if value >= 1e9:
        return f"{value / 1e9:.2f}B"
    if value >= 1e6:
        return f"{value / 1e6:.0f}M"
    if value >= 1e3:
        return f"{value / 1e3:.0f}K"
    return f"{value:.0f}"


def _fmt_distance(distance_pct: float | None) -> str:
    if distance_pct is None:
        return "—"
    return f"{distance_pct * 100:.1f}%"


def _fmt_score(score: float | None) -> str:
    if score is None:
        return "—"
    return f"{score:.1f}"


def render_candidates_table(rows: list[CandidateRow]) -> str | None:
    """Tabla principal con candidatos filtrados.

    Devuelve el ticker de la fila seleccionada o None.

    Decisión: usamos `st.dataframe(on_select="rerun", selection_mode="single-row")`
    (Streamlit >= 1.35). Si el usuario no eligió ninguna fila, devolvemos None.
    """
    st.subheader(f"{len(rows)} candidatos")
    if not rows:
        st.info("Sin candidatos que cumplan los filtros.")
        return None

    df = pd.DataFrame(
        [
            {
                "Ticker": r.ticker,
                # spec 10: composite_label reemplaza tipo_T. Fallback a "{T} (legacy)"
                # para runs históricos sin clasificación dual.
                "Clasificación": (
                    r.composite_label or (f"{r.tipo_T} (legacy)" if r.tipo_T else "—")
                ),
                "Wheel": "🎡" if r.wheel_candidate else "",
                "Spot": format_price(r.spot, r.currency),
                "Sector": r.sector,
                "Score": _fmt_score(r.best_zone_score),
                "Tier": _stars(r.best_zone_tier),
                "Distancia": _fmt_distance(r.best_zone_distance_pct),
                "Strike Natural": (
                    format_price(r.strike_natural, r.currency)
                    if r.strike_natural is not None
                    else "—"
                ),
                "Universos": "+".join(r.universes) if r.universes else "—",
                "Earnings 45d": "Sí" if r.earnings_en_45d else "No",
                "Ex-div 45d": "Sí" if r.ex_div_en_45d else "No",
                "Macro 45d": "Sí" if r.tiene_eventos_macro_en_45d else "No",
            }
            for r in rows
        ]
    )

    event = st.dataframe(
        df,
        on_select="rerun",
        selection_mode="single-row",
        width="stretch",
        hide_index=True,
        key="candidates_table",
    )
    selection = event.selection.rows if event and event.selection else []
    if not selection:
        return None
    return rows[selection[0]].ticker


# --- Detalle ---


def _days_to(target: date | None) -> str:
    if target is None:
        return "—"
    today = date.today()
    delta = (target - today).days
    return f"{target.isoformat()} ({delta:+d}d)"


def render_candidate_detail(detail: CandidateDetail) -> None:
    """Vista de detalle del candidato seleccionado.

    Layout: header → toggle de periodo → chart → tres columnas con
    Paso 1 / Paso 2 / Paso 3 + strikes.
    """
    row = detail.row
    # spec 10: composite_label en lugar del tipo legacy. Fallback para runs históricos.
    header_label = (
        detail.composite_label
        or row.composite_label
        or (f"{row.tipo_T} (legacy)" if row.tipo_T else "")
    )
    wheel_suffix = " 🎡" if detail.wheel_candidate else ""
    st.header(f"{row.ticker} — {header_label}{wheel_suffix}")

    months = st.radio(
        "Periodo",
        options=list(STREAMLIT_CHART_MONTH_OPTIONS),
        index=STREAMLIT_CHART_MONTH_OPTIONS.index(STREAMLIT_DEFAULT_CHART_MONTHS),
        horizontal=True,
        format_func=lambda m: f"{m}m",
        key="period_radio",
    )

    payload = build_chart_payload(detail, months=months)
    if payload is None:
        st.warning("OHLCV no disponible para este ticker en cache.")
    else:
        fig = build_plotly_figure(payload)
        st.plotly_chart(fig, width="stretch")

    st.divider()

    col1, col2, col3 = st.columns(3)
    currency = row.currency

    with col1:
        st.subheader("Paso 1")
        st.markdown(f"**Spot:** {format_price(detail.spot, currency)}")
        st.markdown(f"**Sector:** {row.sector or '—'}")
        st.markdown(f"**País:** {row.country or '—'}")
        st.markdown(f"**Market Cap:** {_fmt_mcap(detail.market_cap)}")
        st.markdown(f"**Momentum Score:** {row.momentum_score}")
        if detail.atr_14 is not None:
            st.markdown(f"**ATR(14):** {detail.atr_14:.2f}")
        if detail.hv_percentile_52w is not None:
            st.markdown(f"**HV pct 52w:** {detail.hv_percentile_52w:.1f}%")
        if detail.rsi_d is not None:
            st.markdown(f"**RSI diario:** {detail.rsi_d:.1f}")
        if detail.rsi_w is not None:
            st.markdown(f"**RSI semanal:** {detail.rsi_w:.1f}")

    with col2:
        st.subheader("Paso 2 — Zona")
        zone = detail.best_zone
        if zone is None:
            st.info("Sin zona válida en Paso 2.")
        else:
            st.markdown(f"**Lower:** {format_price(zone.lower_bound, currency)}")
            st.markdown(f"**Upper:** {format_price(zone.upper_bound, currency)}")
            st.markdown(f"**Score:** {zone.score:.1f}")
            st.markdown(f"**Tier:** {_stars(zone.score_tier)}")
            st.markdown(f"**Distancia:** {zone.distance_pct * 100:.2f}%")
            st.markdown(f"**Confirmador dinámico:** {'sí' if zone.has_dynamic_confirmer else 'no'}")
            st.markdown("**Elementos:**")
            for elem in zone.elements:
                meta_str = ""
                if elem.metadata:
                    meta_items = ", ".join(f"{k}={v}" for k, v in elem.metadata.items())
                    meta_str = f" ({meta_items})"
                st.markdown(f"- {format_price(elem.price, currency)} — {elem.element}{meta_str}")

    with col3:
        st.subheader("Paso 3 — Eventos & Strikes")
        st.markdown(f"**Earnings:** {_days_to(detail.earnings_date)}")
        ex_div_str = _days_to(detail.ex_div_date)
        if detail.ex_div_amount is not None:
            ex_div_str = f"{ex_div_str} — {format_price(detail.ex_div_amount, currency)}"
        st.markdown(f"**Ex-dividend:** {ex_div_str}")
        st.markdown(f"**Eventos macro:** {len(detail.eventos_macro)}")
        if detail.flags_legibles:
            st.markdown("**Flags:**")
            for flag in detail.flags_legibles:
                st.markdown(f"- {flag}")
        st.markdown("---")
        st.markdown("**Strikes**")
        for kind in ("aggressive", "natural", "conservative"):
            value = detail.strikes.get(kind)
            if value is None:
                st.markdown(f"- {kind}: —")
            else:
                st.markdown(f"- {kind}: {format_price(value, currency)}")
        grid_unit = detail.strikes.get("grid_unit")
        if grid_unit is not None:
            st.markdown(f"- grid unit: {grid_unit}")

    if detail.momentum_signals:
        st.info(f"Señales de momentum: {', '.join(detail.momentum_signals)}")

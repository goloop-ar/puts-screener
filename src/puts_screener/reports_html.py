"""Generación del HTML estático con cards rankeadas (§8 de spec 04).

Renderiza `templates/report.html.j2` con Jinja2. Mismo filtro y ordenamiento que el CSV.
Los candidatos se pre-formatean (redondeos) para que el template sea puramente presentacional.
"""

import logging
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from puts_screener.chart_svg import render_mini_chart_svg
from puts_screener.config_reports import (
    JURISDICTION_BY_KIND,
    REPORT_FILENAME_PATTERN,
    REPORT_LATEST_FILENAME,
    REPORT_OUTPUT_DIR,
    SCORE_TIER_LABELS,
)
from puts_screener.config_supports import ELEMENT_WEIGHTS
from puts_screener.formatting import format_price
from puts_screener.macro_calendar import MacroEvent
from puts_screener.models_final import FinalCandidate
from puts_screener.narrative import build_narrative
from puts_screener.reports_csv import element_label, sort_final_candidates
from puts_screener.strikes import compute_heuristic_strikes

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE_NAME = "report.html.j2"


def _format_candidate(fc: FinalCandidate) -> dict:
    """Aplana un FinalCandidate a un dict listo para el template (valores ya redondeados)."""
    screened = fc.supported.screened
    zone = fc.supported.analysis.best_zone
    classification = screened.classification
    analyst = screened.analyst
    tipo = (classification.tipo if classification else "") or ""
    # spec 10: clasificación dual — composite_label reemplaza el badge T1-T5,
    # regime define el color de la card.
    composite_label = screened.composite_label or ""
    regime = screened.regime or ""
    currency = screened.profile.currency or "USD"  # None → fallback USD (defensivo)

    # Elementos ordenados por peso desc (ELEMENT_WEIGHTS); el template muestra los primeros 8.
    elements = [
        {
            "label": element_label(e.element),
            "price": round(e.price, 2),
            "price_formatted": format_price(e.price, currency),
        }
        for e in sorted(zone.elements, key=lambda e: -ELEMENT_WEIGHTS.get(e.element, 0.0))
    ]
    pt_mean = analyst.price_target_mean
    tier = zone.score_tier
    tier_stars, tier_label = SCORE_TIER_LABELS[tier]

    # Strikes heurísticos + mini-chart SVG (spec 07). El OHLCV ya vive en screened (sin re-fetch).
    strikes = compute_heuristic_strikes(
        zone_lower_bound=zone.lower_bound,
        zone_upper_bound=zone.upper_bound,
        zone_center_price=zone.center_price,
        spot=screened.spot,
        atr_14=screened.atr_14,
        currency=currency,
    )
    chart_svg = render_mini_chart_svg(
        ohlcv_daily=screened.ohlcv_daily,
        zone_lower_bound=zone.lower_bound,
        zone_upper_bound=zone.upper_bound,
        strikes=strikes,
        currency=currency,
    )

    return {
        "ticker": fc.ticker,
        "universes": list(screened.universes),
        "sector": screened.profile.sector or "",
        "exchange": screened.profile.exchange or "",
        "tipo_T": tipo,
        "tipo_T_lower": tipo.lower(),
        # spec 10: clasificación dual
        "composite_label": composite_label,
        "regime": regime,
        "primary_trigger": screened.primary_trigger or "",
        "triggers": list(screened.triggers),
        "wheel_candidate": bool(screened.wheel_candidate),
        "currency": currency,
        "spot": round(screened.spot, 2),
        "spot_formatted": format_price(screened.spot, currency),
        "zona_min": round(zone.lower_bound, 2),
        "zona_max": round(zone.upper_bound, 2),
        "zona_min_formatted": format_price(zone.lower_bound, currency),
        "zona_max_formatted": format_price(zone.upper_bound, currency),
        "score": zone.score,
        "score_tier": tier,
        "score_tier_stars": tier_stars,
        "score_tier_label": tier_label,
        "distancia_pct": round(zone.distance_pct * 100, 1),
        "n_elementos": len(zone.elements),
        "elements": elements,
        "rsi_d": round(screened.rsi_d, 1),
        "rsi_w": round(screened.rsi_w, 1),
        "macd_estado": screened.macd_state,
        "momentum_score": screened.momentum_score,
        "price_target": round(pt_mean, 2) if pt_mean is not None else "—",
        "price_target_formatted": format_price(pt_mean, currency) if pt_mean is not None else "—",
        "pt_upside_pct": round(screened.price_target_upside_pct * 100, 1),
        "buy_ratio": round(screened.recommendation_buy_ratio * 100, 1),
        "downgrades": screened.downgrades_6w_count,
        "flags_legibles": list(fc.binary_events.flags_legibles),
        "momentum_signals": list(screened.momentum_signals),
        # Strikes + mini-chart + narrativa (spec 07)
        "strike_aggressive": strikes.aggressive,
        "strike_natural": strikes.natural,
        "strike_conservative": strikes.conservative,
        "strike_aggressive_formatted": format_price(strikes.aggressive, currency),
        "strike_natural_formatted": format_price(strikes.natural, currency),
        "strike_conservative_formatted": format_price(strikes.conservative, currency),
        "chart_svg": chart_svg,
        "chart_placeholder": "" if chart_svg else "Histórico insuficiente para chart",
        "narrative_html": build_narrative(fc),
    }


def _format_macro_events_for_banner(events: list[MacroEvent], today: date) -> list[dict]:
    """Formatea los eventos macro (forward, >= today) para el banner global (§6.5).

    Ordenados por fecha asc. La jurisdicción se infiere del kind vía JURISDICTION_BY_KIND.
    """
    formatted: list[dict] = []
    for e in sorted(events, key=lambda x: x.date):
        if e.date < today:
            continue
        formatted.append(
            {
                "date": e.date.isoformat(),
                "days_until": (e.date - today).days,
                "kind": e.kind,
                "kind_display": e.kind.upper(),
                "description": e.description,
                "jurisdiction": JURISDICTION_BY_KIND.get(e.kind, "—"),
            }
        )
    return formatted


def write_html_report(
    final_candidates: list[FinalCandidate],
    run_metadata: dict,
    output_dir: Path = REPORT_OUTPUT_DIR,
    timestamp: datetime | None = None,
    macro_events: list[MacroEvent] | None = None,
) -> Path:
    """Genera el HTML report (timestamped + latest). Devuelve el path timestamped.

    `macro_events` (spec 06): eventos macro del run en ventana; se renderizan en un banner
    global arriba de las cards (no duplicados per-card).
    """
    timestamp = timestamp or datetime.now()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    included = sort_final_candidates([fc for fc in final_candidates if fc.passes_all_steps])
    candidates = [_format_candidate(fc) for fc in included]
    banner_events = _format_macro_events_for_banner(macro_events or [], timestamp.date())

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template(_TEMPLATE_NAME)
    html = template.render(
        run_date=run_metadata.get("run_date") or f"{timestamp:%Y-%m-%d}",
        universe_size=run_metadata.get("universe_size", 0),
        n_paso_1=run_metadata.get("n_paso_1", 0),
        n_paso_2=run_metadata.get("n_paso_2", 0),
        generated_at=run_metadata.get("generated_at") or timestamp.isoformat(timespec="seconds"),
        version=run_metadata.get("version", "0.1"),
        candidates=candidates,
        macro_events=banner_events,
    )

    stem = REPORT_FILENAME_PATTERN.format(date=f"{timestamp:%Y-%m-%d}", time=f"{timestamp:%H%M}")
    timestamped = output_dir / f"{stem}.html"
    latest = output_dir / f"{REPORT_LATEST_FILENAME}.html"
    timestamped.write_text(html, encoding="utf-8")
    latest.write_text(html, encoding="utf-8")
    logger.info("HTML report written: %s (%d candidates)", timestamped, len(candidates))
    return timestamped

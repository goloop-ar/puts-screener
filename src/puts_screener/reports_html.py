"""Generación del HTML estático con cards rankeadas (§8 de spec 04).

Renderiza `templates/report.html.j2` con Jinja2. Mismo filtro y ordenamiento que el CSV.
Los candidatos se pre-formatean (redondeos) para que el template sea puramente presentacional.
"""

import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from puts_screener.config_reports import (
    REPORT_FILENAME_PATTERN,
    REPORT_LATEST_FILENAME,
    REPORT_OUTPUT_DIR,
)
from puts_screener.models_final import FinalCandidate
from puts_screener.reports_csv import element_label, sort_final_candidates

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

    # Elementos ordenados por puntos desc; el template muestra los primeros 8.
    elements = [
        {"label": element_label(e.element), "price": round(e.price, 2)}
        for e in sorted(zone.elements, key=lambda e: -e.points)
    ]
    pt_mean = analyst.price_target_mean

    return {
        "ticker": fc.ticker,
        "sector": screened.profile.sector or "",
        "exchange": screened.profile.exchange or "",
        "tipo_T": tipo,
        "tipo_T_lower": tipo.lower(),
        "spot": round(screened.spot, 2),
        "zona_min": round(zone.lower_bound, 2),
        "zona_max": round(zone.upper_bound, 2),
        "score": zone.score,
        "distancia_pct": round(zone.distance_pct * 100, 1),
        "n_elementos": len(zone.elements),
        "elements": elements,
        "rsi_d": round(screened.rsi_d, 1),
        "rsi_w": round(screened.rsi_w, 1),
        "macd_estado": screened.macd_state,
        "momentum_score": screened.momentum_score,
        "price_target": round(pt_mean, 2) if pt_mean is not None else "—",
        "pt_upside_pct": round(screened.price_target_upside_pct * 100, 1),
        "buy_ratio": round(screened.recommendation_buy_ratio * 100, 1),
        "downgrades": screened.downgrades_6w_count,
        "flags_legibles": list(fc.binary_events.flags_legibles),
    }


def write_html_report(
    final_candidates: list[FinalCandidate],
    run_metadata: dict,
    output_dir: Path = REPORT_OUTPUT_DIR,
    timestamp: datetime | None = None,
) -> Path:
    """Genera el HTML report (timestamped + latest). Devuelve el path timestamped."""
    timestamp = timestamp or datetime.now()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    included = sort_final_candidates([fc for fc in final_candidates if fc.passes_all_steps])
    candidates = [_format_candidate(fc) for fc in included]

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
    )

    stem = REPORT_FILENAME_PATTERN.format(date=f"{timestamp:%Y-%m-%d}", time=f"{timestamp:%H%M}")
    timestamped = output_dir / f"{stem}.html"
    latest = output_dir / f"{REPORT_LATEST_FILENAME}.html"
    timestamped.write_text(html, encoding="utf-8")
    latest.write_text(html, encoding="utf-8")
    logger.info("HTML report written: %s (%d candidates)", timestamped, len(candidates))
    return timestamped

"""Paso 3 del SOP: detección de eventos binarios (earnings, ex-dividend, macro). Ver §5 de spec 04.

Decisión §2: el screener NO cancela candidatos con eventos binarios — los flagea. El humano
que revisa el reporte decide. Errores aislados por evento: si un fetch falla, ese campo queda
en None y el resto del análisis sigue.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from puts_screener.config_reports import (
    EARNINGS_WINDOW_DAYS,
    EX_DIV_WINDOW_DAYS,
    MACRO_WINDOW_DAYS,
)
from puts_screener.formatting import format_price
from puts_screener.macro_calendar import MacroEvent
from puts_screener.providers.service import DataService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BinaryEventsReport:
    """Resumen de eventos binarios forward-looking de un candidato (§5.1)."""

    # Earnings
    earnings_date: date | None
    dias_a_earnings: int | None
    earnings_en_45d: bool

    # Ex-dividend
    ex_div_date: date | None
    dias_a_ex_div: int | None
    ex_div_en_45d: bool
    ex_div_amount: float | None

    # Macro
    eventos_macro: list[MacroEvent]  # eventos dentro de la ventana
    eventos_macro_en_45d: bool

    # Resumen
    tiene_eventos_binarios: bool  # True si cualquier flag duro está activo
    flags_legibles: list[str]


def check_macro_events(
    today: date,
    calendar: list[MacroEvent],
    window_days: int = MACRO_WINDOW_DAYS,
) -> list[MacroEvent]:
    """Devuelve los eventos del calendario dentro de [today, today + window_days]."""
    horizon = today + timedelta(days=window_days)
    return [e for e in calendar if today <= e.date <= horizon]


def check_binary_events(
    ticker: str,
    today: date,
    data_service: DataService,
    macro_calendar: list[MacroEvent],
    currency: str | None = None,
) -> BinaryEventsReport:
    """Chequea todos los eventos binarios para el ticker (§5.3).

    Errores aislados: si `get_upcoming_earnings` falla, los campos de earnings quedan en None
    y no se propaga al resto del análisis.

    Spec 06: `flags_legibles` contiene SOLO flags per-candidato (earnings + ex-div); los eventos
    macro NO se agregan a las flags (se muestran en el banner global del HTML), aunque el campo
    `eventos_macro` se sigue poblando. `currency` se usa para formatear el monto del ex-dividend.
    """
    # --- Earnings ---
    earnings_date: date | None = None
    dias_a_earnings: int | None = None
    earnings_en_45d = False
    try:
        event = data_service.get_upcoming_earnings(ticker, lookforward_days=EARNINGS_WINDOW_DAYS)
    except Exception as exc:  # noqa: BLE001 — aislamiento por evento, no se propaga
        logger.warning("[%s] get_upcoming_earnings failed: %s", ticker, exc)
        event = None
    if event is not None:
        earnings_date = event.date
        dias_a_earnings = (event.date - today).days
        earnings_en_45d = 0 <= dias_a_earnings <= EARNINGS_WINDOW_DAYS

    # --- Ex-dividend ---
    ex_div_date: date | None = None
    dias_a_ex_div: int | None = None
    ex_div_en_45d = False
    ex_div_amount: float | None = None
    try:
        ex_div = data_service.get_upcoming_ex_dividend(ticker, lookforward_days=EX_DIV_WINDOW_DAYS)
    except Exception as exc:  # noqa: BLE001 — aislamiento por evento, no se propaga
        logger.warning("[%s] get_upcoming_ex_dividend failed: %s", ticker, exc)
        ex_div = None
    if ex_div is not None:
        ex_div_date = ex_div.date
        dias_a_ex_div = (ex_div.date - today).days
        ex_div_en_45d = 0 <= dias_a_ex_div <= EX_DIV_WINDOW_DAYS
        ex_div_amount = ex_div.amount

    # --- Macro ---
    eventos_macro = check_macro_events(today, macro_calendar)
    eventos_macro_en_45d = len(eventos_macro) > 0

    # --- Flags legibles per-candidato (orden de severidad: earnings, ex_div) ---
    # Spec 06: los eventos macro NO van acá (se muestran en el banner global del run).
    flags: list[str] = []
    if earnings_en_45d and earnings_date is not None:
        flags.append(f"Earnings en {dias_a_earnings} días ({earnings_date.isoformat()})")
    if ex_div_en_45d:
        if ex_div_amount is not None:
            flags.append(
                f"Ex-dividend en {dias_a_ex_div} días ({format_price(ex_div_amount, currency)})"
            )
        else:
            flags.append(f"Ex-dividend en {dias_a_ex_div} días")

    tiene_eventos_binarios = earnings_en_45d or ex_div_en_45d or eventos_macro_en_45d

    return BinaryEventsReport(
        earnings_date=earnings_date,
        dias_a_earnings=dias_a_earnings,
        earnings_en_45d=earnings_en_45d,
        ex_div_date=ex_div_date,
        dias_a_ex_div=dias_a_ex_div,
        ex_div_en_45d=ex_div_en_45d,
        ex_div_amount=ex_div_amount,
        eventos_macro=eventos_macro,
        eventos_macro_en_45d=eventos_macro_en_45d,
        tiene_eventos_binarios=tiene_eventos_binarios,
        flags_legibles=flags,
    )

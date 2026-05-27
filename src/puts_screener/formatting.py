"""Helpers de formateo compartidos por la capa de reportes (spec 06 §6.4).

`format_price` vive acá (no en reports_html) porque también lo usa `binary_events.py` para
el flag de ex-dividend — un módulo compartido evita el import circular.
"""

from puts_screener.config_reports import CURRENCY_DEFAULT, CURRENCY_DISPLAY


def format_price(value: float, currency: str | None) -> str:
    """Formatea un precio con el símbolo monetario correcto según la currency del ticker.

    Ejemplos:
        format_price(150.23, "USD") → "$150.23"
        format_price(453.55, "GBp") → "453.55p"
        format_price(82.10, "EUR")  → "€82.10"
        format_price(42.00, None)   → "$42.00"  (fallback USD)
    """
    cfg = CURRENCY_DISPLAY.get(currency, CURRENCY_DEFAULT)
    adjusted = value / cfg["divisor"]
    return f"{cfg['prefix']}{adjusted:.2f}{cfg['suffix']}"

"""Narrativa técnica heurística por candidato (spec 07 §6.3).

Tres párrafos HTML (situación, zona, qué mirar) generados con plantillas deterministas desde
los campos ya disponibles del FinalCandidate. Función pura: no persiste, no consulta red ni
disco. Pensada para inyectarse en el template con |safe (Tanda 4).
"""

from puts_screener.config_supports import ELEMENT_WEIGHTS, HEAVY_ELEMENT_WEIGHT_THRESHOLD
from puts_screener.formatting import format_price
from puts_screener.models_final import FinalCandidate
from puts_screener.models_support import SupportZone
from puts_screener.strikes import compute_heuristic_strikes

_TIPO_DESCRIPTION: dict[str, str] = {
    "T1": "tendencia alcista intacta con pullback a soporte",
    "T2": "pánico de mercado o spike de IV",
    "T3": "lateralización en zona técnica",
    "T4": "post-earnings dip con tendencia intacta",
    "T5": "wheel / acumulación",
}

# DUPLICACIÓN INTENCIONAL del label de tier para no acoplar la narrativa a la capa de display.
# Copiado del 2º elemento de cada tupla de SCORE_TIER_LABELS (vive en config_reports, NO en
# config_supports como decía la spec §6.3). Si SCORE_TIER_LABELS cambia, actualizar acá.
_TIER_LABEL: dict[int, str] = {
    5: "Confluencia excepcional",
    4: "Fuerte",
    3: "Sólida",
    2: "Borderline",
    1: "Mínimo viable",
}

_ELEMENT_CATEGORY: dict[str, str] = {
    "sma_200d": "sma_200",
    "sma_200w": "sma_200",
    "ema_200d": "sma_200",
    "sma_50d": "sma_50",
    "sma_50w": "sma_50",
    "ema_50d": "sma_50",
    "polarity": "polarity",
    "avwap_pivot_low": "avwap",
    "avwap_earnings": "avwap",
    "avwap_52w_high": "avwap",
    "hvn": "hvn",
}

_CATEGORY_PHRASE: dict[str, str] = {
    "sma_200": "la SMA200 como referencia institucional de largo plazo",
    "sma_50": "la SMA50 como soporte de mediano plazo",
    "polarity": "una resistencia rota previamente que ahora opera como soporte",
    "hvn": "un nodo de alto volumen en la zona (acumulación previa)",
}

_AVWAP_ANCHOR: dict[str, str] = {
    "avwap_pivot_low": "el último pivot bajo",
    "avwap_earnings": "earnings",
    "avwap_52w_high": "el máximo de 52 semanas",
}


def _avwap_anchor_label(element: str) -> str:
    return _AVWAP_ANCHOR.get(element, "el ancla")


def _heavies_categories_dedup(zone: SupportZone) -> list[str]:
    """Categorías heavy únicas presentes en la zona, en orden de aparición.

    Solo cuenta elementos con peso >= HEAVY_ELEMENT_WEIGHT_THRESHOLD; los livianos
    (hvn, sma_50w, ema_50d, avwap_52w_high, fibs, gap, divergence) no aportan.
    """
    cats: list[str] = []
    for e in zone.elements:
        if ELEMENT_WEIGHTS.get(e.element, 0.0) < HEAVY_ELEMENT_WEIGHT_THRESHOLD:
            continue
        cat = _ELEMENT_CATEGORY.get(e.element)
        if cat and cat not in cats:
            cats.append(cat)
    return cats


def _narrative_situation(fc: FinalCandidate) -> str:
    screened = fc.supported.screened
    classification = screened.classification
    tipo = classification.tipo if classification else None
    if tipo is None:
        return ""

    sentences = [
        f"<strong>Situación.</strong> {fc.ticker} está en un contexto "
        f"<strong>{tipo}</strong> ({_TIPO_DESCRIPTION.get(tipo, 'situación técnica')})."
    ]
    if screened.rsi_d < 50 and screened.rsi_d > screened.rsi_d_3d_ago:
        sentences.append(
            f"RSI diario en {screened.rsi_d:.0f} con giro al alza "
            f"desde {screened.rsi_d_3d_ago:.0f}."
        )
    if screened.macd_state.startswith("subiendo"):
        sentences.append("MACD virando a positivo.")
    if screened.rsi_d >= 70:
        sentences.append(f"Atención: RSI diario en zona de sobrecompra ({screened.rsi_d:.0f}).")
    return "<p>" + " ".join(sentences) + "</p>"


def _narrative_zone(fc: FinalCandidate) -> str:
    zone = fc.supported.analysis.best_zone
    screened = fc.supported.screened
    currency = screened.profile.currency or "USD"

    if zone.width_pct < 0.02:
        width_q = "compacta"
    elif zone.width_pct < 0.035:
        width_q = "ajustada"
    else:
        width_q = "amplia"

    phrases: list[str] = []
    for cat in _heavies_categories_dedup(zone):
        if cat == "avwap":
            for e in zone.elements:
                if (
                    _ELEMENT_CATEGORY.get(e.element) == "avwap"
                    and ELEMENT_WEIGHTS.get(e.element, 0.0) >= HEAVY_ELEMENT_WEIGHT_THRESHOLD
                ):
                    anchor = _avwap_anchor_label(e.element)
                    phrases.append(
                        f"el AVWAP desde {anchor} como precio promedio de acumulación reciente"
                    )
                    break
        else:
            phrase = _CATEGORY_PHRASE.get(cat)
            if phrase:
                phrases.append(phrase)

    n_heavy = len(phrases)
    if n_heavy == 0:
        anchor_sentence = ""
    elif n_heavy == 1:
        anchor_sentence = f"Anclada en {phrases[0]}."
    else:
        anchor_sentence = f"Anclada en {n_heavy} elementos heavy: " + "; ".join(phrases) + "."

    if zone.distance_pct < 0.08:
        dist_q = "dentro del rango operable"
    else:
        dist_q = "al límite del rango operable"

    low_str = format_price(zone.lower_bound, currency)
    high_str = format_price(zone.upper_bound, currency)

    sentences = [
        f"<strong>Zona.</strong> La zona detectada está en {low_str} – {high_str} "
        f"(ancho {zone.width_pct * 100:.1f}%, {width_q})."
    ]
    tier_label = _TIER_LABEL.get(zone.score_tier, "")
    if tier_label:
        sentences.append(f"Es una <strong>{tier_label}</strong>.")
    if anchor_sentence:
        sentences.append(anchor_sentence)
    sentences.append(
        f"El precio está a {zone.distance_pct * 100:.1f}% del techo de la zona, {dist_q}."
    )
    return "<p>" + " ".join(sentences) + "</p>"


def _narrative_what_to_watch(fc: FinalCandidate) -> str:
    screened = fc.supported.screened
    binary = fc.binary_events
    zone = fc.supported.analysis.best_zone
    currency = screened.profile.currency or "USD"

    # Recomputa los strikes acá (en vez de recibirlos del dict de _format_candidate, Tanda 4) para
    # que la narrativa sea función pura del candidato y testeable sin la capa de render.
    strikes = compute_heuristic_strikes(
        zone.lower_bound,
        zone.upper_bound,
        zone.center_price,
        screened.spot,
        screened.atr_14,
        currency,
    )
    conservative_str = format_price(strikes.conservative, currency)
    sentences = [
        "<strong>Qué mirar.</strong>",
        f"Si el precio cierra debajo del conservative ({conservative_str}), "
        f"conviene revisar la tesis.",
    ]

    has_event = False
    if binary.earnings_en_45d and binary.dias_a_earnings is not None:
        has_event = True
        sentences.append(
            f"Earnings en {binary.dias_a_earnings} días — considerar dimensionar la posición "
            f"para evento o evitar strikes que asignen alrededor del reporte."
        )
    if binary.ex_div_en_45d and binary.dias_a_ex_div is not None:
        has_event = True
        amount_str = f" (${binary.ex_div_amount:.2f})" if binary.ex_div_amount is not None else ""
        sentences.append(
            f"Ex-dividend en {binary.dias_a_ex_div} días{amount_str} — riesgo de asignación "
            f"temprana del put si la opción queda ITM en esa fecha."
        )
    if binary.eventos_macro_en_45d and binary.eventos_macro:
        has_event = True
        kinds = ", ".join(sorted({ev.kind for ev in binary.eventos_macro}))
        sentences.append(f"Eventos macro en ventana: {kinds}.")
    if not has_event:
        sentences.append("Sin eventos binarios ni macro en ventana — situación técnica limpia.")
    return "<p>" + " ".join(sentences) + "</p>"


def build_narrative(candidate: FinalCandidate) -> str:
    """3 párrafos HTML describiendo situación, zona y qué mirar.

    Función pura. No persiste. Si algún campo es None o la situación no aplica, omite limpio
    las oraciones afectadas — nunca deja placeholders huérfanos.

    Returns:
        String con 3 elementos <p>, uno por párrafo, separados por "\\n". Cada <p> arranca con
        un <strong> con la etiqueta del párrafo. Si el candidato no tiene best_zone (no debería
        pasar — solo se llama sobre passes_all_steps=True), devuelve "".
    """
    zone = candidate.supported.analysis.best_zone
    if zone is None:
        return ""
    p1 = _narrative_situation(candidate)
    p2 = _narrative_zone(candidate)
    p3 = _narrative_what_to_watch(candidate)
    return "\n".join(p for p in [p1, p2, p3] if p)

"""Tests de strikes estructurales (spec 11 §8 / tanda 2).

Zonas construidas a mano con SupportLevel explícitos. Sin llamadas a APIs ni a la DB.
"""

from __future__ import annotations

from puts_screener.models_reports import StructuralStrikes
from puts_screener.models_support import SupportLevel, SupportZone
from puts_screener.strike_placement import compute_structural_strikes, extract_heavy_anchors

# --- Helpers ---


def make_zone(
    lower: float,
    upper: float,
    elements: list[SupportLevel],
    *,
    score: float = 10.0,
) -> SupportZone:
    return SupportZone(
        center_price=(lower + upper) / 2,
        lower_bound=lower,
        upper_bound=upper,
        score=score,
        elements=elements,
        has_dynamic_confirmer=True,
        distance_pct=0.02,
    )


# --- extract_heavy_anchors ---


class TestExtractHeavyAnchors:
    def test_filtra_por_peso_y_ordena_por_precio(self) -> None:
        elements = [
            SupportLevel(price=98.0, element="sma_200d"),  # heavy (3.0), desordenado a propósito
            SupportLevel(price=90.0, element="fib_618"),  # liviano (1.5), no debe aparecer
            SupportLevel(price=94.0, element="ema_200d"),  # heavy (2.5)
            SupportLevel(price=85.0, element="gap_unfilled"),  # liviano (1.0), no debe aparecer
            SupportLevel(price=96.0, element="avwap_pivot_low"),  # heavy (2.5)
        ]
        zone = make_zone(80.0, 100.0, elements)
        anchors = extract_heavy_anchors(zone)
        assert [a.element for a in anchors] == ["ema_200d", "avwap_pivot_low", "sma_200d"]
        assert [a.price for a in anchors] == [94.0, 96.0, 98.0]


# --- Orden conservative < natural < aggressive < spot, por variante ---


class TestVariantOrdering:
    def _zone(self) -> SupportZone:
        elements = [
            SupportLevel(price=90.0, element="sma_200d"),
            SupportLevel(price=95.0, element="ema_200d"),
            SupportLevel(price=88.0, element="fib_618"),  # liviano: no es ancla, pero baja bounds
        ]
        return make_zone(85.0, 100.0, elements)

    def test_variant_a_orden_correcto(self) -> None:
        s = compute_structural_strikes(
            self._zone(), spot=150.0, atr_14=2.0, currency="USD", variant="A"
        )
        assert s.conservative < s.natural < s.aggressive < 150.0
        assert s.anchor_kind == "heavy_element"

    def test_variant_b_orden_correcto(self) -> None:
        s = compute_structural_strikes(
            self._zone(), spot=150.0, atr_14=2.0, currency="USD", variant="B"
        )
        assert s.conservative < s.natural < s.aggressive < 150.0
        assert s.anchor_kind == "heavy_element"

    def test_variant_c_orden_correcto(self) -> None:
        s = compute_structural_strikes(
            self._zone(), spot=150.0, atr_14=2.0, currency="USD", variant="C"
        )
        assert s.conservative < s.natural < s.aggressive < 150.0
        assert s.anchor_kind == "zone_bound"

    def test_variant_a_lower_bound_por_debajo_de_heavy_no_invierte_orden(self) -> None:
        # Caso encontrado al implementar: lower_bound = min(TODOS los elementos) - buffer, así
        # que puede caer bien por debajo de heavy_lowest cuando hay un elemento liviano más bajo
        # aún. Si eso invirtiera conservative/natural, el enforcement de orden debe corregirlo.
        elements = [
            SupportLevel(price=95.0, element="sma_200d"),  # heavy_lowest
            SupportLevel(price=98.0, element="ema_200d"),  # heavy_highest
            SupportLevel(price=70.0, element="fib_618"),  # liviano, arrastra lower_bound muy abajo
        ]
        zone = make_zone(65.0, 100.0, elements)
        s = compute_structural_strikes(zone, spot=150.0, atr_14=2.0, currency="USD", variant="A")
        assert s.conservative < s.natural < s.aggressive < 150.0


# --- Variantes D/E/F (tanda 2): los 3 niveles en o debajo de lower_bound ---


class TestVariantsDEF:
    def _zone(self) -> SupportZone:
        # misma composición que TestVariantOrdering._zone: heavy_lowest=90 (sma_200d),
        # heavy_highest=95 (ema_200d), lower_bound=85 < heavy_lowest (invariante estructural).
        elements = [
            SupportLevel(price=90.0, element="sma_200d"),
            SupportLevel(price=95.0, element="ema_200d"),
            SupportLevel(price=88.0, element="fib_618"),
        ]
        return make_zone(85.0, 100.0, elements)

    def test_variant_d_orden_correcto_y_valores(self) -> None:
        s = compute_structural_strikes(
            self._zone(), spot=95.0, atr_14=2.0, currency="USD", variant="D"
        )
        assert (s.conservative, s.natural, s.aggressive) == (82.0, 83.0, 84.0)
        assert s.conservative < s.natural < s.aggressive < 95.0
        assert s.anchor_kind == "zone_bound"
        assert s.conservative_anchor == s.aggressive_anchor == "zone_lower_bound"

    def test_variant_e_orden_correcto_y_valores(self) -> None:
        s = compute_structural_strikes(
            self._zone(), spot=95.0, atr_14=2.0, currency="USD", variant="E"
        )
        assert (s.conservative, s.natural, s.aggressive) == (82.0, 83.0, 84.0)
        assert s.conservative < s.natural < s.aggressive < 95.0
        assert s.anchor_kind == "zone_bound"  # lower_bound(85) < heavy_lowest(90): gana la zona

    def test_variant_f_orden_correcto_y_valores(self) -> None:
        # F.conservative calibrado a -3.0*ATR (D11.12/Tanda 3, único intento pre-declarado:
        # -2.0*ATR daba 83.9% de aguante a 45d, -3.0*ATR alcanzó 89.0% >= target 88%).
        s = compute_structural_strikes(
            self._zone(), spot=95.0, atr_14=2.0, currency="USD", variant="F"
        )
        assert (s.conservative, s.natural, s.aggressive) == (79.0, 83.0, 84.0)
        assert s.conservative < s.natural < s.aggressive < 95.0
        assert s.anchor_kind == "zone_bound"

    def test_def_aggressive_queda_en_o_debajo_de_lower_bound(self) -> None:
        # La razón de ser de D/E/F: a diferencia de A/B/C (aggressive puede quedar DENTRO de la
        # zona), acá los 3 niveles caen a <= lower_bound.
        zone = self._zone()
        for variant in ("D", "E", "F"):
            s = compute_structural_strikes(
                zone, spot=95.0, atr_14=2.0, currency="USD", variant=variant
            )
            assert s.aggressive <= zone.lower_bound, f"variant {variant}: {s.aggressive}"

    def test_variant_e_min_elige_heavy_cuando_esta_bajo_lower_bound(self) -> None:
        # Caso sintético (no ocurre en zonas reales del pipeline, donde lower_bound siempre es
        # <= heavy_lowest): prueba que _min_base_anchor elige el heavy cuando gana el min().
        elements = [SupportLevel(price=80.0, element="sma_200d")]
        zone = make_zone(85.0, 100.0, elements)
        s = compute_structural_strikes(zone, spot=95.0, atr_14=1.0, currency="USD", variant="E")
        assert s.anchor_kind == "heavy_element"
        assert s.conservative_anchor == "sma_200d"
        assert s.aggressive_anchor == "sma_200d"
        assert s.conservative < s.natural < s.aggressive < 95.0

    def test_variant_d_no_requiere_heavy_pero_igual_hace_fallback_sin_el(self) -> None:
        # D no usa heavy en su fórmula, pero la regla de fallback es uniforme entre variantes.
        elements = [SupportLevel(price=95.0, element="fib_618")]  # liviano, no heavy
        zone = make_zone(90.0, 96.0, elements)
        s = compute_structural_strikes(zone, spot=100.0, atr_14=2.0, currency="USD", variant="D")
        assert s.anchor_kind == "fallback_atr"
        assert s.variant == "D"


# --- Redondeo hacia abajo, para las 4 grillas de divisa ---


class TestRoundingAlwaysDown:
    # Variante A, buffer aggressive=0: aggressive = heavy_highest.price exacto (atr_14=0),
    # así que el resultado aísla el comportamiento de redondeo puro. Los valores se eligen para
    # que floor y "redondeo al más cercano" difieran, y así probar que es floor de verdad.

    def test_grid_usd(self) -> None:
        elements = [
            SupportLevel(price=95.0, element="sma_200d"),
            SupportLevel(price=101.9, element="ema_200d"),  # /2.5=40.76 -> nearest daría 102.5
        ]
        zone = make_zone(90.0, 110.0, elements)
        s = compute_structural_strikes(zone, spot=150.0, atr_14=0.0, currency="USD", variant="A")
        assert s.grid_unit == 2.5
        assert s.aggressive == 100.0  # floor, no 102.5

    def test_grid_eur(self) -> None:
        elements = [
            SupportLevel(price=95.0, element="sma_200d"),
            SupportLevel(price=101.9, element="ema_200d"),
        ]
        zone = make_zone(90.0, 110.0, elements)
        s = compute_structural_strikes(zone, spot=150.0, atr_14=0.0, currency="EUR", variant="A")
        assert s.grid_unit == 2.5
        assert s.aggressive == 100.0

    def test_grid_gbp(self) -> None:
        elements = [
            SupportLevel(price=95.0, element="sma_200d"),
            SupportLevel(price=101.9, element="ema_200d"),
        ]
        zone = make_zone(90.0, 110.0, elements)
        s = compute_structural_strikes(zone, spot=150.0, atr_14=0.0, currency="GBP", variant="A")
        assert s.grid_unit == 2.5
        assert s.aggressive == 100.0

    def test_grid_gbp_pence(self) -> None:
        elements = [
            SupportLevel(price=4900.0, element="sma_200d"),
            SupportLevel(price=5199.0, element="ema_200d"),  # /100=51.99 -> nearest daría 5200
        ]
        zone = make_zone(4800.0, 5250.0, elements)
        s = compute_structural_strikes(zone, spot=5300.0, atr_14=0.0, currency="GBp", variant="A")
        assert s.grid_unit == 100.0
        assert s.aggressive == 5100.0  # floor, no 5200.0


# --- Colapso de grilla ---


class TestGridCollapse:
    def test_colapso_se_separa_por_grid_unit(self) -> None:
        elements = [
            SupportLevel(price=95.0, element="sma_200d"),  # heavy_lowest
            SupportLevel(price=97.4, element="ema_200d"),  # heavy_highest, cerca del lowest
        ]
        zone = make_zone(85.0, 100.0, elements)
        # Variante B, atr=6.0: natural=95.0 y aggressive=97.4-0.6=96.8 flotan al mismo escalón de
        # grilla (2.5 -> ambos a 95.0) antes del enforcement de orden.
        s = compute_structural_strikes(zone, spot=150.0, atr_14=6.0, currency="USD", variant="B")
        assert s.grid_unit == 2.5
        assert s.conservative == 90.0
        assert s.natural == 92.5
        assert s.aggressive == 95.0
        assert s.natural == s.aggressive - s.grid_unit
        assert s.conservative < s.natural < s.aggressive


# --- Fallback sin elementos heavy ---


class TestFallbackSinHeavy:
    def test_zona_sin_heavy_cae_a_fallback_atr(self) -> None:
        elements = [
            SupportLevel(price=95.0, element="fib_618"),
            SupportLevel(price=93.0, element="gap_unfilled"),
        ]
        zone = make_zone(90.0, 96.0, elements)
        s = compute_structural_strikes(zone, spot=100.0, atr_14=2.0, currency="USD", variant="B")
        assert isinstance(s, StructuralStrikes)
        assert s.anchor_kind == "fallback_atr"
        assert s.aggressive_anchor is None
        assert s.conservative_anchor is None
        assert s.variant == "B"  # se preserva la variante pedida aunque no se haya usado
        assert s.conservative < s.natural < s.aggressive < 100.0

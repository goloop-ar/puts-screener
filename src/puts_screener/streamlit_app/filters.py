"""Filtros aplicables a la lista de `CandidateRow` (spec 09 §X — tanda 1).

Función pura sobre la lista en memoria. No re-consulta la DB; tampoco re-ordena: el
orden de entrada (score desc, ver `data_loader.load_run_candidates`) se preserva.
"""

from dataclasses import dataclass

from puts_screener.streamlit_app.models import CandidateRow


@dataclass(frozen=True)
class FilterState:
    """Estado de los filtros. Vacíos / None significa "no filtrar por ese criterio"."""

    tier: frozenset[str] = frozenset()
    sector: frozenset[str] = frozenset()
    score_min: float = 0.0
    requires_earnings_in_45d: bool | None = None
    requires_ex_div_in_45d: bool | None = None
    requires_macro_in_45d: bool | None = None


def apply_filters(rows: list[CandidateRow], state: FilterState) -> list[CandidateRow]:
    """Aplica los filtros del `FilterState`. Preserva el orden de entrada.

    Semántica:
    - `tier` / `sector`: si el set es vacío, no filtra; sino exige pertenencia.
    - `score_min`: si > 0, exige `best_zone_score >= score_min` (rows con score None
      se excluyen). Si == 0, no filtra y los None se incluyen.
    - `requires_*_in_45d`: si None, ignora el flag; si True/False, exige match exacto.
    """
    result: list[CandidateRow] = []
    for row in rows:
        if state.tier and row.tipo_T not in state.tier:
            continue
        if state.sector and row.sector not in state.sector:
            continue
        if state.score_min > 0 and (
            row.best_zone_score is None or row.best_zone_score < state.score_min
        ):
            continue
        if (
            state.requires_earnings_in_45d is not None
            and row.earnings_en_45d != state.requires_earnings_in_45d
        ):
            continue
        if (
            state.requires_ex_div_in_45d is not None
            and row.ex_div_en_45d != state.requires_ex_div_in_45d
        ):
            continue
        if (
            state.requires_macro_in_45d is not None
            and row.tiene_eventos_macro_en_45d != state.requires_macro_in_45d
        ):
            continue
        result.append(row)
    return result

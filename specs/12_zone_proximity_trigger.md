# Spec 12 — Trigger de proximidad a zona (unifica `pullback_in_uptrend` + `range_floor`)

> Estado: aprobada, en implementación. Fecha: 2026-09-07.
>
> **Nota de contrato**: esta spec es la conclusión de tres sesiones de diagnóstico sobre el issue
> de ROADMAP §2 "`range_floor` con 0/36 detecciones en `regime=lateral`". El diseño no parte de
> intuición — cada decisión de §11 tiene un número que la respalda, medido sobre las 1113
> clasificaciones históricas (`regime IS NOT NULL`, filtro D11.8 de spec 11) y sobre las 36 zonas
> `lateral` afectadas. El peso final de `zone_proximity` (§11, D12.6) se fijó después de simular la
> reclasificación completa dos veces (con 0.7 y con 0.4) y verificar contra la DB real, no antes.
> Los scripts de diagnóstico quedaron en `scratch/` (gitignored, no productivos):
> `diagnose_range_floor.py`, `diagnose_range_floor_outcome.py`, `diagnose_lateral_sensitivity.py`.

---

## 1. Objetivo

Dos triggers del catálogo de spec 10 miden, en el fondo, la misma cosa — "¿el precio está cerca
de una zona de soporte validada de buena calidad?" — pero quedaron separados artificialmente por
régimen:

- **`pullback_in_uptrend`** (solo `regime=uptrend`): `best_zone.score >= SCORE_MIN_VALID` (5.0) y
  `best_zone.distance_pct <= MAX_DISTANCE_TO_SUPPORT_PCT` (10%).
- **`range_floor`** (solo `regime=lateral`): las mismas dos condiciones de zona **no están**, en
  cambio exige que el cierre esté en el tercio inferior de un rango de 60 días hábiles calculado
  **independientemente de la zona**.

Esa condición extra de `range_floor` es la causa de que nunca haya disparado: el precio al que se
satisface el tercio inferior del rango de 60d cae, en el 100% de los 36 casos históricos
observados, por debajo del precio al que la zona misma se invalida por `ZONE_MIN_DISTANCE_PCT=3%`
(spec 02). Para cuando el precio bajaría lo suficiente para `range_floor`, la `best_zone` que
sostiene todo el candidato ya fue rechazada en Paso 2 — el candidato ni siquiera llega a
`classify_candidate`. 0 detecciones en 4.5 meses / 85 runs; 36 candidatos de score alto
descartados silenciosamente (30 solo en agosto).

Esta spec **unifica ambos en un único trigger `zone_proximity`**, aplicable en cualquier régimen,
con las dos condiciones que ya usa `pullback_in_uptrend` (sin agregar ningún umbral nuevo — cero
superficie nueva para repetir esta clase de bug). El régimen pasa a ser puramente descriptivo
(alimenta `composite_label`), nunca un gate para este trigger. Es, además, el trigger más débil
del catálogo (§11, D12.6): dice solo que hay una zona validada cerca, algo cierto para el 100% de
los candidatos que pasan Paso 2 — cede ante cualquier trigger que nombre una causa concreta
(estructura o evento) y actúa como piso de último recurso.

### Regla metodológica (continúa la de spec 11)

Antes de tocar código se corrió el diagnóstico completo tres veces: primero sobre los 36 casos de
`range_floor` (causa raíz), después sobre las 1113 clasificaciones históricas para medir el blast
radius de aflojar `evaluate_regime`, y por último la simulación de reclasificación completa con dos
pesos candidatos (0.7 y 0.4) para elegir el de `zone_proximity` con datos, no con intuición. La
decisión de **no tocar `evaluate_regime`** (D12.5) sale directamente de la segunda medición.

---

## 2. Scope

### En scope

- Nuevo evaluador `evaluate_zone_proximity` en `classification_v2.py`, regime-agnóstico.
- Retiro de `evaluate_range_floor` y `evaluate_pullback_in_uptrend`.
- Actualización de `TRIGGER_REGIME_COMPAT`, `TRIGGER_WEIGHTS`, `TRIGGER_LABELS`,
  `PRIMARY_TRIGGER_TO_LEGACY_TIPO` en `config_classification_v2.py`.
- Retiro de `RANGE_FLOOR_LOOKBACK_DAYS` / `RANGE_FLOOR_BOTTOM_THIRD` (sin reemplazo — `zone_proximity`
  no necesita constantes propias).
- Actualización de `streamlit_app/views.py` (opciones del filtro de trigger primario).
- Validación retroactiva sobre las 1113 clasificaciones + los 36 casos `lateral`, corrida
  **después** de implementar, como regresión (§9).

### Fuera de scope

- **Tocar `evaluate_regime` o sus umbrales** (`REGIME_LATERAL_TOLERANCE_PCT`,
  `REGIME_LATERAL_RANGE_DAYS`, `REGIME_LATERAL_MAX_RANGE_PCT`). Decisión D12.5: blast radius medido,
  el punto que hubiera decidido salió N=21 (no concluyente), y aflojar diluye `lateral` con ~101
  `pullback` de rango ancho (20-25%, casi el doble del rango real de los 36 casos) más 27
  `double_bottom` de `downtrend` que ya tienen trigger propio calibrado.
- **Recalibrar el peso de `post_earnings_dip` o `hma_weekly_flip`**, pese a los hallazgos D12.4/
  D12.8/D12.9: `post_earnings_dip` estaba sistemáticamente tapado por `pullback_in_uptrend` (0.7 >
  0.6) y esta spec lo destapa por primera vez (69 disparos en `triggers_json`, solo 4 como primary
  hasta ahora); `hma_weekly_flip` dispara 112 veces pero gana primary solo 3. Ambos quedan
  anotados como observación para una sesión de recalibración con datos de outcome (backtest), no
  como acción de esta spec.
- Cambiar el gate de salida a Paso 3 (`primary_trigger is not None` en `final_pipeline.py`).
- `capitulation_reclaim` u otros issues de ROADMAP §2 — no tocados.
- No determinismo de `evaluate_regime` (issue nuevo de esta sesión, ver ROADMAP §2) — issue
  separado, no se arregla acá.

---

## 3. Decisiones de parametrización

**Cero constantes nuevas.** `evaluate_zone_proximity` reusa exactamente las mismas dos que ya usa
`evaluate_pullback_in_uptrend` hoy, definidas en `config_supports.py` (spec 02/Etapa 4):

| Constante | Valor | Origen |
| --- | --- | --- |
| `SCORE_MIN_VALID` | `5.0` | `config_supports.py`, ya usada por Paso 2 y por `pullback_in_uptrend`. |
| `MAX_DISTANCE_TO_SUPPORT_PCT` | `0.10` | `config_supports.py`, ídem. |

Contraste explícito con lo que se retira: `range_floor` traía dos constantes propias
(`RANGE_FLOOR_LOOKBACK_DAYS=60`, `RANGE_FLOOR_BOTTOM_THIRD=0.33`) calibradas en spec 10 sin
verificar su interacción con `ZONE_MIN_DISTANCE_PCT` de spec 02 — el origen exacto del bug. No
tener constantes propias en `zone_proximity` elimina esa clase de choque por construcción: no hay
un segundo umbral independiente con el que `ZONE_MIN_DISTANCE_PCT` pueda chocar.

`TRIGGER_WEIGHTS["zone_proximity"] = 0.4` — ver §11, D12.6, para la justificación completa.

---

## 4. Modelos / dataclasses

Ninguno nuevo. `TriggerHit` (`name: str`, `weight: float`, `metadata: dict`) ya cubre el caso —
`zone_proximity` emite un `TriggerHit` igual que cualquier otro trigger. `RegimeEvaluation` no
cambia: el régimen se sigue calculando exactamente igual, solo deja de gatear este trigger.

---

## 5. APIs públicas

```python
# src/puts_screener/classification_v2.py

def evaluate_zone_proximity(
    *,
    regime: Regime,
    best_zone_score: float | None,
    best_zone_distance_pct: float | None,
) -> TriggerHit | None:
    """zone_proximity: best_zone con score válido + distancia OK, en cualquier régimen.

    Mismas dos condiciones que el actual pullback_in_uptrend (§3), sin restricción de régimen.
    El régimen se recibe solo para el chequeo de compatibilidad (TRIGGER_REGIME_COMPAT), que
    para este trigger incluye los 4 valores — es un no-op en la práctica, pero mantiene el mismo
    patrón defensivo que usan los demás evaluadores.
    """
```

**Retirados**: `evaluate_pullback_in_uptrend`, `evaluate_range_floor`. Ninguno de los dos queda
como fallback ni deprecated — a diferencia de `compute_heuristic_strikes` en spec 11, acá no hay
"reproducir output histórico" que preservar: `range_floor` nunca disparó (0 filas en toda la DB
con `primary_trigger='range_floor'` ni presente en `triggers_json` de ninguna fila), y
`pullback_in_uptrend` se reemplaza 1:1 por `zone_proximity` con las mismas condiciones — no hay
comportamiento nuevo que reproducir desde el viejo.

---

## 6. Algoritmos

### 6.1 `evaluate_zone_proximity`

Idéntico al cuerpo actual de `evaluate_pullback_in_uptrend`, salvo el diccionario de
compatibilidad:

```
1. Si regime not in TRIGGER_REGIME_COMPAT["zone_proximity"] → None.  (siempre True: los 4 regímenes)
2. Si best_zone_score is None or best_zone_distance_pct is None → None.
3. Si best_zone_score < SCORE_MIN_VALID → None.
4. Si best_zone_distance_pct > MAX_DISTANCE_TO_SUPPORT_PCT → None.
5. Emitir TriggerHit(name="zone_proximity", weight=TRIGGER_WEIGHTS["zone_proximity"], metadata={...}).
```

### 6.2 `classify_candidate` — orquestador

Se elimina el bloque de `pullback_in_uptrend` de su posición actual (primero en la lista `hits`,
spec 10) y se reemplaza por `evaluate_zone_proximity`, **movido al final** de los bloques que
compiten por `primary` (después de `post_earnings_dip`, antes del modificador
`bullish_divergence`). No es solo cosmético: con peso 0.4 no hay ningún otro trigger con el mismo
valor, así que el tie-breaker por orden de inserción de `select_primary_trigger` nunca se ejecuta
para `zone_proximity` en la práctica — pero moverlo al final hace que el código narre su propio
rol: "primero se prueban las causas nombradas, `zone_proximity` es el piso que queda si ninguna
disparó". Se elimina el bloque de `range_floor` sin reemplazo — su condición queda cubierta por
`zone_proximity`.

### 6.3 `legacy_tipo` — mapeo condicionado por régimen (solo para `zone_proximity`)

`PRIMARY_TRIGGER_TO_LEGACY_TIPO` hoy es un `dict[str, str]` plano (trigger → T). Eso alcanzaba
porque cada trigger vivía en un solo régimen. `zone_proximity` dispara en los 4, y el mapeo T
legacy pre-spec-10 distinguía por régimen+contexto (T1=uptrend pullback, T3=lateral), así que un
mapeo plano lo aplanaría mal (todo a un solo T, perdiendo la distinción que el propio legacy
schema quería capturar). Se agrega un caso especial en el punto donde se computa `legacy_tipo`:

```python
_ZONE_PROXIMITY_LEGACY_TIPO_BY_REGIME: dict[Regime, str] = {
    "uptrend": "T1",
    "lateral": "T3",
    "downtrend": "T2",   # mismo T2 que double_bottom/capitulation en downtrend
    "reversal": "T2",    # mismo T2 que double_bottom/capitulation/hma_flip en reversal
}

legacy_tipo = (
    _ZONE_PROXIMITY_LEGACY_TIPO_BY_REGIME.get(regime)
    if primary and primary.name == "zone_proximity"
    else PRIMARY_TRIGGER_TO_LEGACY_TIPO.get(primary.name) if primary else None
)
```

`tipo_T` es un vehículo de backcompat ya marcado para eliminación (ROADMAP §4, "`TypeClassification`
deprecation completa") — este es el mínimo necesario para no romper su semántica mientras siga
vivo, sin invertir en más lógica de un campo que se va a borrar.

---

## 7. Persistencia

**Sin migración.** `candidates.triggers_json`, `candidates.primary_trigger` y
`candidates.composite_label` ya son columnas `TEXT` libres (spec 10) — aceptan cualquier string de
trigger sin cambio de schema. `_CANDIDATE_MIGRATION_COLUMNS` no gana entradas.

Runs históricos conservan `primary_trigger='pullback_in_uptrend'` / `'range_floor'` (aunque este
último con 0 filas reales) tal como están — no se reescribe la DB. Mismo criterio que spec 10 con
los labels T1-T5: el dato histórico es un registro de lo que el código calculó en ese momento, no
se migra retroactivamente. Runs nuevos (post-implementación) usan `'zone_proximity'`.

`Streamlit` (`streamlit_app/views.py`, `_PRIMARY_TRIGGER_OPTIONS`) tiene una lista hardcodeada de
triggers para el multiselect del sidebar — se actualiza agregando `"zone_proximity"` y sacando
`"range_floor"`; `"pullback_in_uptrend"` se mantiene en la lista para poder seguir filtrando runs
históricos (no hay razón para que un usuario pierda la capacidad de filtrar corridas viejas por su
trigger real).

---

## 8. Tests

### Unitarios — `tests/test_classification_v2.py`

- `evaluate_zone_proximity`: dispara en cada uno de los 4 regímenes con el mismo
  score/distance (parametrizado) — este es el test que prueba explícitamente que dejó de ser un
  gate. Rechaza con `score < 5.0`. Rechaza con `distance_pct > 0.10`. Rechaza con
  `score`/`distance_pct` en `None`.
- `classify_candidate`, `zone_proximity` pierde contra `double_bottom_unconfirmed` cuando ambos
  disparan (0.4 < 0.5) → `primary_trigger` debe ser `double_bottom_unconfirmed`. Documenta
  explícitamente que los 155 casos históricos de esta transición NO cambian con el peso elegido.
- `classify_candidate`, `zone_proximity` pierde contra `post_earnings_dip` cuando ambos disparan
  (0.4 < 0.6) → `primary_trigger` debe ser `post_earnings_dip`. Test explícito pedido: es el
  hallazgo D12.9 (69 disparos, 4 primarios hasta ahora, tapado por el `pullback_in_uptrend` viejo)
  y la transición real de 61 casos históricos — sin este test, una futura recalibración de pesos
  podría romperlo en silencio.
- `classify_candidate`, `double_bottom_confirmed` sigue ganando sobre `zone_proximity` cuando
  ambos disparan (1.0 > 0.4) — no-regresión, el trigger más fuerte no cambia.
- `classify_candidate`, `zone_proximity` gana cuando es el único trigger con `weight > 0` que
  disparó — su rol de piso de último recurso, el caso que recupera los 36 históricos.
- `legacy_tipo` para `zone_proximity`: los 4 regímenes mapean a T1/T2/T2/T3 respectivamente
  (uptrend/downtrend/reversal/lateral) vía `_ZONE_PROXIMITY_LEGACY_TIPO_BY_REGIME`.
- Retirar (o adaptar) los tests existentes de `evaluate_pullback_in_uptrend` y
  `evaluate_range_floor` — sus casos base migran a `evaluate_zone_proximity` parametrizado por
  régimen.

### Validación retroactiva — POST-implementación, sobre el dataset real

A diferencia de spec 11 (donde la tasa de detección se midió *antes* de integrar), acá la
validación retroactiva se corre **después** de implementar, como chequeo de regresión — la
implementación es lo bastante simple (reusa condiciones ya existentes) como para no necesitar un
gate previo, pero sí necesita confirmarse contra la DB real al cerrar, no asumirse:

1. Sobre las 1113 clasificaciones históricas (`regime IS NOT NULL`), recomputar `primary_trigger`
   con el código nuevo (no una simulación aparte — el mismo `classify_candidate` real, con
   `best_zone.score`/`best_zone.distance_pct` ya persistidos; no requiere OHLCV nuevo).
2. **Criterio de aceptación 1**: los 36 casos `regime=lateral` (36/36) deben terminar con
   `primary_trigger='zone_proximity'`.
3. **Criterio de aceptación 2**: 0 de los 1113 candidatos que hoy tienen `primary_trigger` no nulo
   terminan con `primary_trigger=None` (nadie deja de llegar al output).
4. Reportar la tabla completa de transiciones y contrastarla contra la de §11 D12.4 (que fue
   simulada, no ejecutada con el código real) — deben coincidir exactamente; si no coinciden, el
   código tiene un bug respecto del diseño.

---

## 9. Criterios de aceptación

- [ ] `evaluate_zone_proximity` implementado, función pura, mismo estilo que los demás
      evaluadores de `classification_v2.py`.
- [ ] `evaluate_pullback_in_uptrend` y `evaluate_range_floor` retirados (no quedan colgando ni
      como dead code).
- [ ] **Validación retroactiva post-implementación: 36/36 de los casos históricos
      `regime=lateral` disparan `zone_proximity` como primario, corrida sobre el dataset real
      con el código nuevo** (no una simulación previa — ver §8).
- [ ] **Validación retroactiva post-implementación: 0/1113 candidatos que hoy llegan al output
      (`primary_trigger` no nulo) dejan de llegar**, corrida sobre el dataset real.
- [ ] La tabla de transiciones real (post-implementación) coincide con la simulada en D12.4.
- [ ] Tests explícitos de ordenamiento de pesos: `zone_proximity` pierde contra
      `double_bottom_unconfirmed` y contra `post_earnings_dip`, gana contra nada (piso de último
      recurso).
- [ ] Suite verde, sin regresiones sobre los 630 tests existentes (post spec 11).
- [ ] `streamlit_app/views.py` actualizado, filtro de trigger primario sigue funcionando sobre
      runs viejos y nuevos.
- [ ] ROADMAP §1/§2/§3/§5 + contadores reales actualizados al cierre.

---

## 10. Archivos a crear / modificar

```
src/puts_screener/
├── classification_v2.py         [MOD]  evaluate_zone_proximity reemplaza evaluate_pullback_in_uptrend
│                                        + evaluate_range_floor; movido al final del orden de
│                                        evaluación; legacy_tipo condicionado por régimen
├── config_classification_v2.py  [MOD]  TRIGGER_REGIME_COMPAT, TRIGGER_WEIGHTS (zone_proximity=0.4),
│                                        TRIGGER_LABELS, PRIMARY_TRIGGER_TO_LEGACY_TIPO; retira
│                                        RANGE_FLOOR_*
└── streamlit_app/views.py       [MOD]  _PRIMARY_TRIGGER_OPTIONS

tests/
└── test_classification_v2.py    [MOD]  tests de evaluate_zone_proximity + ordenamiento de pesos
                                         (incluye zone_proximity vs post_earnings_dip explícito)

scratch/
├── diagnose_range_floor.py           [YA EXISTE]  diagnóstico causa raíz (esta sesión)
├── diagnose_range_floor_outcome.py   [YA EXISTE]  outcome de los 36 casos (esta sesión)
├── diagnose_lateral_sensitivity.py   [YA EXISTE]  blast radius de régimen + reclasificación (0.7)
└── validate_zone_proximity.py        [NUEVO]      validación retroactiva post-implementación (§8/§9)

specs/
└── 12_zone_proximity_trigger.md      [MOD]  este doc (peso 0.4, tabla corregida)

Sin cambios: config_supports.py (SCORE_MIN_VALID/MAX_DISTANCE_TO_SUPPORT_PCT ya existen),
persistence.py (sin migración), reports_csv.py/reports_html.py/narrative.py (leen primary_trigger/
composite_label como strings genéricos, no hardcodean nombres de trigger), templates/report.html.j2.
```

---

## 11. Decisiones registradas

**D12.1 — Causa raíz de `range_floor`: choque con `ZONE_MIN_DISTANCE_PCT`, no bug de código ni
umbral simplemente mal puesto.** Diagnóstico completo (turno previo a esta spec): un fixture
sintético que cumple las 3 condiciones de `evaluate_range_floor` por diseño SÍ dispara (bug
descartado). El caso más cercano de los 36 reales solo necesitaba ~1.7% más de caída (no es un
umbral "20x lejos" — descarta threshold-mal-calibrado-aislado como causa primaria). En 36/36
casos, el precio al que `range_floor` dispararía implica `distance_pct < ZONE_MIN_DISTANCE_PCT`
(3%) — la zona ya sería inválida en Paso 2 antes de llegar ahí. Choque estructural entre dos
umbrales calibrados en specs distintas (spec 02 y spec 10) que nadie vio leyendo cada uno por
separado.

**D12.2 — `pullback_in_uptrend` y un `range_floor` redefinido contra la zona miden lo mismo.**
`evaluate_pullback_in_uptrend` no tiene condición geométrica propia más allá de
`best_zone.distance_pct <= 10%`, y `distance_pct = (spot - zone.upper_bound) / spot`
(`zone_clustering.py:136`) — literalmente "qué tan cerca está el precio del techo de la zona". Un
`range_floor` que midiera "cerca de la zona" en vez de "cerca del piso de un rango de 60d
independiente" sería la misma condición con otro nombre, distinguida solo por el régimen en el que
se le permite disparar. De ahí la unificación en un solo trigger.

**D12.3 — `pullback_in_uptrend` se absorbe en `zone_proximity`, no se retira sin reemplazo.** Es
el trigger primario de 716/1113 (64.3%) de las clasificaciones históricas — la columna vertebral
del output actual. Retirarlo sin reemplazo vaciaría la mayoría del output; absorberlo en
`zone_proximity` preserva el mismo comportamiento en `uptrend` (mismas dos condiciones, aunque con
el peso 0.4 puede ceder ante `post_earnings_dip` cuando ambos disparan — ver D12.9) y lo extiende a
los otros 3 regímenes.

**D12.4 — Blast radius de la unificación con peso 0.4: 752/1113 (67.6%) cambian de
`primary_trigger`, 0 pierden output.** Medido simulando la reclasificación completa sobre las 1113
filas (`scratch/diagnose_lateral_sensitivity.py`, recorrido con `zone_proximity=0.4`):

| transición | N |
| --- | --- |
| `pullback_in_uptrend` → `zone_proximity` | 655 |
| `pullback_in_uptrend` → `post_earnings_dip` | 61 |
| `None` → `zone_proximity` | **36** (recuperados) |
| (cualquiera) → `None` | **0** |

Sin cambio de primario (se conservan tal cual): los 155 `double_bottom_unconfirmed` (0.5 > 0.4,
ver D12.2 del intento anterior con peso 0.7 — con 0.4 esto ya no ocurre), y el resto de los 1113
(`double_bottom_confirmed`, `capitulation_reclaim`, y los casos donde ningún trigger nuevo
compite).

Esta tabla reemplaza la de un intento previo con `zone_proximity=0.7`, donde la predicción inicial
("716 sin cambio, 155 conservan") solo se cumplió a medias: con 0.7, los 155
`double_bottom_unconfirmed` efectivamente pasaban a `zone_proximity` (0.7 > 0.5), un efecto no
buscado. Bajar el peso a 0.4 corrige exactamente eso (D12.6) — pero expone una segunda transición
no anticipada, los 61 `pullback_in_uptrend → post_earnings_dip` (D12.9), verificada como correcta
y esperada, no como bug.

**D12.5 — No se tocan los umbrales de `evaluate_regime`.** Blast radius medido para 6 combinaciones
de `(REGIME_LATERAL_TOLERANCE_PCT, REGIME_LATERAL_MAX_RANGE_PCT)`, de (0.03,0.15) actual hasta
(0.10,0.25). La pregunta que hubiera decidido — ¿el grupo que se reclasificaría a `lateral` aguanta
igual, mejor o peor que el que se queda en `uptrend`? — salió **N=21, no concluyente** (mínimo
declarado: 30). Además, la combinación más agresiva probada diluye `lateral` con 101 candidatos
`pullback_in_uptrend` de rango 60d 20-25% (casi el doble del 12-14% real de los 36 casos
originales) y 27 `double_bottom` de `downtrend` que ya tienen trigger propio calibrado. Sin
evidencia de que aflojar el régimen mejore nada y con evidencia de que lo diluye, no se toca. Esta
spec resuelve el problema real (candidatos perdidos) sin necesitar tocar `evaluate_regime`.

**D12.6 — Peso de `zone_proximity` = 0.4 (revisado; el borrador original proponía 0.7).**
`zone_proximity` es un trigger **genérico de posición**: dice que el precio está cerca de una zona
validada, algo cierto para el 100% de los candidatos que llegan a `classify_candidate` (ya pasaron
Paso 2). No dice nada sobre la *forma* del ticker. Los demás triggers con peso ≥0.5 nombran una
**causa** — estructura (`double_bottom_*`, `capitulation_reclaim`, `hma_weekly_flip`) o evento
(`post_earnings_dip`) — información que "cerca de zona" no aporta. La regla de diseño:
**`zone_proximity` cede ante cualquier trigger que nombre una causa**, sea estructural o de
evento, no solo ante los estructurales.

El primer intento (0.7, igual al `pullback_in_uptrend` retirado) heredaba sin revisar un orden de
pesos calibrado en spec 10 cuando `pullback_in_uptrend` y `double_bottom_unconfirmed` vivían en
regímenes distintos y **nunca competían** — desacoplar el régimen expuso esa comparación por
primera vez, y con 0.7 el resultado era que 155 candidatos con un doble piso en formación
mostraban "cerca de zona" como label primario en vez de "doble piso en formación", perdiendo
especificidad. Simulado, verificado, y corregido antes de implementar (D12.4).

Con 0.4, `zone_proximity` queda por debajo de **todos** los triggers con causa nombrada
(`double_bottom_unconfirmed`/`hma_weekly_flip`=0.5, `post_earnings_dip`=0.6,
`capitulation_reclaim`=0.9, `double_bottom_confirmed`=1.0) y gana **solo cuando ninguna causa fue
identificada** — exactamente su rol: el piso que evita que un candidato con zona validada se caiga
del output por no tener trigger nombrado, sin opacar a los triggers que sí dicen algo específico.

**D12.7 — Nombre `zone_proximity`.** Describe la condición geométrica (distancia a la zona), no el
régimen en el que aplica — consistente con el resto del catálogo (`double_bottom`,
`capitulation_reclaim`, `hma_weekly_flip` nombran el patrón detectado, no el contexto de régimen).
`pullback_in_uptrend` horneaba el régimen en el nombre, que es exactamente el acoplamiento que esta
spec deshace.

**D12.8 — Observación (no acción): `hma_weekly_flip` dispara 112 veces en `triggers_json` pero
gana `primary` solo 3.** Con `zone_proximity=0.4` esto no cambia (0.4 < 0.5). El desbalance
109-vs-3 es preexistente a esta spec y sugiere que su peso 0.5 merece revisión en algún momento con
datos de outcome (backtest) — no se toca acá, queda anotado para una sesión aparte (ver ROADMAP §4
existente sobre recalibración de `TRIGGER_WEIGHTS`).

**D12.9 — Hallazgo: `post_earnings_dip` era un trigger invisible, no uno de baja frecuencia.**
Verificado sobre las 1113 filas: `post_earnings_dip` aparece en `triggers_json` 69 veces pero gana
`primary` solo 4 — estaba sistemáticamente tapado por `pullback_in_uptrend` (0.7 > 0.6), el único
trigger que le ganaba en peso y que competía en su mismo régimen (`uptrend`) con mucha más
frecuencia. Con `zone_proximity=0.4 < post_earnings_dip=0.6`, esta spec lo destapa: 61 de esos 69
casos pasan a mostrar `post_earnings_dip` como primario (verificado, ejemplos reales: `BKT.MC`,
`HOOD`, `ANET`, mayo-junio 2026). Es el comportamiento correcto y esperado según D12.6 (evento
nombrado > posición genérica), no un efecto secundario — pero es una consecuencia real de esta
spec que vale la pena tener registrada: el output va a mostrar `post_earnings_dip` mucho más
seguido de lo que la frecuencia histórica de "primary" sugería.

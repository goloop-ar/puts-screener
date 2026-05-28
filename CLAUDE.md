# CLAUDE.md — Reglas operativas del proyecto

> Este archivo te da el contexto del proyecto. Leelo siempre antes de empezar cualquier tarea.

## Colaboración con Claude (chat) sobre este repo

Estas reglas aplican a **Claude (chat)** (la instancia web/mobile con la que colaboro fuera de
Claude Code), no a Claude Code.

1. **No inferir estructura del repo.** Cuando Claude (chat) tenga dudas sobre cómo está
   estructurado el código, qué archivos existen, dónde vive una función, o cualquier detalle del
   filesystem, no debe adivinar ni asumir. Debe pedirme que le consulte a Claude Code,
   entregándome un prompt listo para que yo se lo pase.
2. **Siempre entregar prompts copy-paste.** Cuando Claude (chat) necesite que yo le pase algo a
   Claude Code (consultas, instrucciones, pedidos de código), debe darme el prompt ya redactado,
   listo para copiar y pegar; nunca pedirme que lo escriba yo a mano. El prompt debe venir
   **dentro de un bloque de código** (triple backtick), no como texto plano en el cuerpo del
   mensaje, para que se copie con un solo click desde el botón de copiar del bloque y no requiera
   selección manual de texto.

### Estilo de colaboración: acción antes que explicación

Cuando el usuario ya entendió el contexto y confirmó dirección, Claude (chat) debe priorizar
entregar el prompt copy-paste o el siguiente paso accionable sobre re-explicar el razonamiento.
Specifically:

- No re-justificar decisiones ya tomadas en turnos previos de la misma sesión.
- No expandir trade-offs que ya se discutieron, salvo que el usuario pregunte explícitamente.
- Si una decisión técnica menor surge mid-tanda y no cambia el alcance, tomarla con criterio y
  avanzar (anotándola en el reporte post-tanda o en §5 del ROADMAP al cierre). No interrumpir
  para validar cada micro-decisión.
- Reportes de cierre de tanda: hash + tests + push + 1-2 líneas de fricciones reales. No
  re-narrar lo que el prompt ya describía.
- Si algo sale mal en la ejecución, se arregla después — no se previene con explicaciones
  exhaustivas en cada turno.
- Cuando el usuario ya confirmó dirección ("dale", "vamos con X", "hagámoslo"), el turno
  siguiente debe arrancar directamente con el accionable (prompt copy-paste, edición concreta,
  comando a correr). Análisis y diagnóstico van DESPUÉS del accionable o se omiten si la
  decisión es obvia desde el contexto. No "análisis → propuesta → pedido de confirmación"
  cuando ya hay confirmación previa en la sesión.
- "Lo que NO hago" / trade-offs descartados: incluir solo si son no-obvios o si el usuario
  podría razonablemente esperar la alternativa. Si son evidentes desde el contexto, omitir.
- Una sola pregunta por turno cuando se necesita input; nunca encadenar "¿confirmás esto?
  ¿y también esto otro?".

Esto optimiza tokens de Claude y agiliza el ciclo de iteración. Aplica a Claude (chat); Claude
Code mantiene su nivel de detalle actual en reportes de ejecución (eso sí necesita verbosidad
para que Claude chat tenga contexto fiel del filesystem real).

## Antes de cualquier trabajo

1. Leé `SPEC.md` para entender visión, scope, output esperado y vocabulario.
2. Si la tarea está asociada a una spec específica en `specs/NN_xxx.md`, leéla completa.
3. Si algo no está claro o ambiguo, **preguntá antes de codear**. No asumas.

## Stack y versiones

- Python 3.11+
- Package manager: `pip` con `venv` estándar (no poetry/uv salvo que el usuario lo pida explícitamente)
- Testing: `pytest`
- Linting + format: `ruff` (todo-en-uno)
- Core data: `pandas`, `numpy`
- Indicadores técnicos: numpy/pandas puro (no `pandas-ta`)
- HTTP: `requests`
- Templating HTML: `jinja2`

## Estructura del proyecto

```
puts-screener/
├── SPEC.md
├── CLAUDE.md
├── README.md
├── requirements.txt
├── specs/               # Specs implementables, una por feature
├── src/puts_screener/   # Todo el código de la app vive acá
├── tests/               # Tests con pytest, espejando src/
├── data/                # SQLite + caches (se commitea)
└── output/              # CSVs y HTMLs generados (se commitea)
```

Nada de código de aplicación en la raíz.

## Reglas de código

- Type hints en funciones públicas siempre que se pueda.
- Docstrings cortos en funciones no triviales, estilo Google.
- No comentarios obvios. Comentar el "por qué", no el "qué".
- Una función = una responsabilidad. Si pasa de 40 líneas, partila.
- Imports al tope agrupados: stdlib, third-party, local.
- No magic numbers. Constantes con nombre.
- Manejo de errores explícito en llamadas a APIs externas (timeouts, retries, fallbacks).

## Reglas de testing

- Cada feature nueva viene con tests.
- Tests en `tests/`, espejando estructura de `src/`.
- Tests deterministas: usar fixtures con data fija, no llamadas live a APIs.
- Para APIs externas: mockear con `responses` o `pytest-mock`.
- Correr tests: `pytest -v` desde la raíz.
- Cobertura objetivo: lógica de negocio crítica (scoring, clasificación, detección de soportes) debe estar testeada.

## Datos sensibles

- API keys NUNCA en el código.
- Desarrollo local: `.env` con `python-dotenv`. `.env` debe estar en `.gitignore`.
- En GitHub Actions: GitHub Secrets.

## Convención de commits

Conventional commits:

- `feat: add Stooq OHLCV provider`
- `fix: handle missing FCF in yfinance response`
- `refactor: extract pivot detection module`
- `test: add support scoring tests`
- `chore: bump pandas-ta`
- `docs: update SPEC with phase 2 scope`

Un commit = un cambio lógico. No commits gigantes mezclando cosas.

## Cuándo preguntar antes de actuar

- Instalar dependencias nuevas que no están en `requirements.txt`
- Modificar `SPEC.md` o `CLAUDE.md`
- Crear archivos fuera del scope de la tarea actual
- Refactors grandes que tocan múltiples módulos
- Cambiar interfaces ya usadas por otros módulos
- Borrar archivos

## Cuándo NO preguntar (avanzá directo)

- Implementar lo que pide la spec actual
- Agregar tests
- Fix de typos en docstrings/comentarios
- Formatear con ruff

## Principio de diseño clave

Todas las fuentes de data van detrás de una clase abstracta `DataProvider`. La lógica de negocio (scoring, clasificación, filtros) nunca llama directo a yfinance/Stooq/Finnhub. Esto se define formalmente en `specs/01_data_providers.md`.

## Al terminar una tarea, reportá

- Qué hiciste (resumen 2-3 líneas)
- Archivos creados/modificados (lista)
- Cómo testear lo hecho (comando concreto)
- Decisiones que tomaste y por qué (si aplica)
- Cosas que quedaron pendientes o ambiguas

## Al cerrar una sesión de trabajo

Una "sesión" es un bloque de conversación que termina con un feature/spec/fix cerrado
o con el usuario explicitando que va a cerrar. Antes de terminar:

1. **ROADMAP.md actualizado**: §1 refleja lo completado en la sesión, §2 limpio de
   issues ya resueltos, §3 con el próximo paso refinado, §4 con items movidos/cerrados,
   §5 con decisiones nuevas registradas. "Última actualización" en fecha de hoy.
2. **Contadores refrescados con datos reales** (no estimados): correr `pytest --tb=no -q`
   para el conteo de tests y `git rev-list --count main` para commits. Usar esos números
   exactos en §1 Estadísticas.
3. **Specs y docs afectados al día**: cualquier spec que se cerró marcada como tal,
   cualquier doc con referencia stale (cron schedule, paths, etc.) corregido.
4. **Commit + push del sweep de cierre**: el sweep va en su propio commit con mensaje
   `docs(roadmap): close <feature>, refresh stats, ...` (o similar). Push directo a main.
5. **Working tree puede quedar dirty con artefactos de smoke** (output/, data/*.db).
   Esos no entran al commit de cierre; el cron los regenera y sincroniza.

Razón: el usuario sube ROADMAP/CLAUDE/SPEC/specs al knowledge al arrancar cada chat
nuevo. Si la sesión cierra con docs stale, el siguiente chat empieza con info incorrecta
y la primera tarea termina siendo un sweep correctivo — pérdida de tiempo evitable.

## Comandos útiles

```bash
# Setup inicial (primera vez)
python -m venv .venv
source .venv/bin/activate         # macOS/Linux
# .venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Tests
pytest -v

# Formato + lint
ruff format src/ tests/
ruff check src/ tests/

# Correr el screener (cuando exista)
python -m puts_screener.run
```

# Puts Screener

Automatización del screening diario de acciones para venta sistemática de puts en mercados US y Europa.

Ver [`SPEC.md`](SPEC.md) para detalles del proyecto y [`CLAUDE.md`](CLAUDE.md) para reglas de desarrollo.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
python -m puts_screener.run
```

Outputs en `output/` y `data/`.

## Estado

En desarrollo activo. Fase 1 (MVP local).

"""Construcción del bundle de GitHub Pages (Fase 3, spec 05 §5/§6).

Toma el contenido de `output/` (reportes de spec 04) y arma un bundle estático: el último run
como home (`index.html`), un índice navegable del histórico (`history.html`) y los archivos
timestamped + CSVs descargables bajo `history/`.

Entry point: `python -m puts_screener.publish_pages [--output OUTPUT] [--bundle BUNDLE]`.
"""

import argparse
import logging
import re
import shutil
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from puts_screener.config_publishing import (
    HISTORY_SORT_DESCENDING,
    PAGES_HISTORY_FILENAME,
    PAGES_HISTORY_SUBDIR,
    PAGES_INDEX_FILENAME,
    PAGES_LATEST_CSV_FILENAME,
    PAGES_OUTPUT_DIR,
    REPORT_FILENAME_REGEX,
)
from puts_screener.models_publishing import HistoryEntry, PagesBundle

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_NAME = "history.html.j2"
DEFAULT_TEMPLATE_PATH = TEMPLATE_DIR / TEMPLATE_NAME

_LATEST_HTML = "screening_latest.html"
_LATEST_CSV = "screening_latest.csv"
_FILENAME_RE = re.compile(REPORT_FILENAME_REGEX)

_PLACEHOLDER_INDEX = (
    "<!DOCTYPE html>\n"
    '<html lang="es"><head><meta charset="utf-8"><title>Puts Screener</title></head>'
    "<body><h1>Puts Screener</h1><p>Esperando primer run.</p></body></html>\n"
)


def discover_history(output_dir: Path) -> list[HistoryEntry]:
    """Escanea output_dir buscando archivos que matchean REPORT_FILENAME_REGEX.

    Empareja .html con su .csv gemelo (mismo date+time). Si solo existe uno de los dos, igual
    genera HistoryEntry con el que esté presente, pero descarta las entries sin HTML. Ignora
    silenciosamente cualquier otro archivo (incluidos screening_latest.*).

    Returns:
        Lista ordenada según HISTORY_SORT_DESCENDING.
    """
    if not output_dir.exists():
        return []

    entries_by_key: dict[tuple[date, str], dict[str, str]] = {}
    for path in output_dir.iterdir():
        match = _FILENAME_RE.fullmatch(path.name)
        if not match:
            continue
        date_str, hhmm, ext = match.groups()
        key = (date.fromisoformat(date_str), hhmm)
        entries_by_key.setdefault(key, {})[ext] = path.name

    result = [
        HistoryEntry(
            run_date=run_date,
            run_time=run_time,
            html_filename=files.get("html"),  # type: ignore[arg-type]  # filtrado abajo
            csv_filename=files.get("csv"),
        )
        for (run_date, run_time), files in entries_by_key.items()
    ]
    result = [entry for entry in result if entry.html_filename is not None]
    result.sort(key=lambda entry: entry.sort_key, reverse=HISTORY_SORT_DESCENDING)
    return result


def render_history_index(
    entries: list[HistoryEntry],
    template_path: Path,
) -> str:
    """Renderiza el HTML del índice del histórico.

    Los hrefs son relativos al documento (sin barra inicial) → funcionan tanto en root
    como en project page (subpath /<repo>/) sin necesidad de base URL configurable.
    """
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template(template_path.name)
    return template.render(entries=entries)


def build_pages_bundle(
    output_dir: Path,
    bundle_dir: Path,
    *,
    template_path: Path | None = None,
) -> PagesBundle:
    """Construye el bundle completo en bundle_dir (ver §6.2)."""
    template_path = template_path or DEFAULT_TEMPLATE_PATH

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)
    history_dir = bundle_dir / PAGES_HISTORY_SUBDIR
    history_dir.mkdir()

    index_html = bundle_dir / PAGES_INDEX_FILENAME
    latest_html_src = output_dir / _LATEST_HTML
    if latest_html_src.exists():
        shutil.copyfile(latest_html_src, index_html)
    else:
        logger.warning("No %s en %s — escribiendo index placeholder", _LATEST_HTML, output_dir)
        index_html.write_text(_PLACEHOLDER_INDEX, encoding="utf-8")

    latest_csv: Path | None = None
    latest_csv_src = output_dir / _LATEST_CSV
    if latest_csv_src.exists():
        latest_csv = bundle_dir / PAGES_LATEST_CSV_FILENAME
        shutil.copyfile(latest_csv_src, latest_csv)

    entries = discover_history(output_dir)
    for entry in entries:
        shutil.copyfile(output_dir / entry.html_filename, history_dir / entry.html_filename)
        if entry.csv_filename:
            shutil.copyfile(output_dir / entry.csv_filename, history_dir / entry.csv_filename)

    history_html = bundle_dir / PAGES_HISTORY_FILENAME
    history_html.write_text(
        render_history_index(entries, template_path),
        encoding="utf-8",
    )

    logger.info(
        "Bundle armado en %s: index=%s, history=%s (%d entries), latest_csv=%s",
        bundle_dir,
        index_html.name,
        history_html.name,
        len(entries),
        latest_csv.name if latest_csv else "—",
    )
    return PagesBundle(
        bundle_dir=bundle_dir,
        index_html=index_html,
        history_html=history_html,
        latest_csv=latest_csv,
        history_entries=tuple(entries),
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point CLI. Returns exit code."""
    parser = argparse.ArgumentParser(description="Build the GitHub Pages bundle from output/")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Directorio de reportes (default: output)",
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=PAGES_OUTPUT_DIR,
        help=f"Directorio destino del bundle (default: {PAGES_OUTPUT_DIR})",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    build_pages_bundle(args.output, args.bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests de la capa de publicación a Pages (spec 05 §9.1)."""

from datetime import date

from puts_screener.publish_pages import (
    DEFAULT_TEMPLATE_PATH,
    build_pages_bundle,
    discover_history,
    render_history_index,
)


def _write(path, content="x"):
    path.write_text(content, encoding="utf-8")


def _timestamped(output_dir, date_str, hhmm, *, html=True, csv=True, html_content="x"):
    """Crea un par timestamped (html/csv) en output_dir."""
    if html:
        _write(output_dir / f"screening_{date_str}_{hhmm}.html", html_content)
    if csv:
        _write(output_dir / f"screening_{date_str}_{hhmm}.csv")


# --- discover_history ---


def test_discover_history_empty_dir(tmp_path):
    assert discover_history(tmp_path) == []


def test_discover_history_only_latest(tmp_path):
    _write(tmp_path / "screening_latest.html")
    _write(tmp_path / "screening_latest.csv")
    assert discover_history(tmp_path) == []


def test_discover_history_paired_html_csv(tmp_path):
    _timestamped(tmp_path, "2026-05-20", "2200")
    _timestamped(tmp_path, "2026-05-21", "2200")
    _timestamped(tmp_path, "2026-05-22", "2200")
    entries = discover_history(tmp_path)
    assert len(entries) == 3
    # Orden descendente: más reciente primero.
    assert [e.run_date for e in entries] == [
        date(2026, 5, 22),
        date(2026, 5, 21),
        date(2026, 5, 20),
    ]
    assert all(e.csv_filename is not None for e in entries)
    assert entries[0].html_filename == "screening_2026-05-22_2200.html"


def test_discover_history_html_only(tmp_path):
    _timestamped(tmp_path, "2026-05-22", "2200", csv=False)
    entries = discover_history(tmp_path)
    assert len(entries) == 1
    assert entries[0].html_filename == "screening_2026-05-22_2200.html"
    assert entries[0].csv_filename is None


def test_discover_history_csv_only(tmp_path):
    _timestamped(tmp_path, "2026-05-22", "2200", html=False)
    # Sin HTML gemelo → la entry se filtra.
    assert discover_history(tmp_path) == []


def test_discover_history_ignores_garbage(tmp_path):
    _write(tmp_path / "notes.txt")
    _write(tmp_path / "screening_invalid.html")
    _write(tmp_path / "screening_2026-05-22.html")  # falta el HHMM
    _write(tmp_path / "random.csv")
    _write(tmp_path / "screening_latest.html")
    _timestamped(tmp_path, "2026-05-22", "2200")  # único válido
    entries = discover_history(tmp_path)
    assert len(entries) == 1
    assert entries[0].run_date == date(2026, 5, 22)


# --- render_history_index ---


def test_render_history_index_with_entries(tmp_path):
    _timestamped(tmp_path, "2026-05-22", "2200")
    _timestamped(tmp_path, "2026-05-21", "1830")
    entries = discover_history(tmp_path)
    html = render_history_index(entries, DEFAULT_TEMPLATE_PATH)
    assert "<table" in html
    assert "2026-05-22" in html
    assert "22:00" in html
    assert "2026-05-21" in html
    assert "18:30" in html


def test_render_history_index_empty(tmp_path):
    html = render_history_index([], DEFAULT_TEMPLATE_PATH)
    assert "Sin corridas registradas" in html


# --- build_pages_bundle ---


def test_build_pages_bundle_full(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    _write(output / "screening_latest.html", "LATEST_RUN_MARKER")
    _write(output / "screening_latest.csv", "ticker,score\n")
    _timestamped(output, "2026-05-22", "2200")
    _timestamped(output, "2026-05-21", "2200")

    bundle_dir = tmp_path / "docs-build"
    result = build_pages_bundle(output, bundle_dir)

    # Estructura del bundle.
    assert (bundle_dir / "index.html").exists()
    assert (bundle_dir / "history.html").exists()
    assert (bundle_dir / "screening_latest.csv").exists()
    assert (bundle_dir / "history" / "screening_2026-05-22_2200.html").exists()
    assert (bundle_dir / "history" / "screening_2026-05-22_2200.csv").exists()
    assert (bundle_dir / "history" / "screening_2026-05-21_2200.html").exists()
    # index.html = copia de screening_latest.html.
    assert (bundle_dir / "index.html").read_text(encoding="utf-8") == "LATEST_RUN_MARKER"
    # PagesBundle reporta las entries (2) y los paths.
    assert len(result.history_entries) == 2
    assert result.latest_csv is not None
    assert result.index_html == bundle_dir / "index.html"


def test_build_pages_bundle_no_latest(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    _timestamped(output, "2026-05-22", "2200")  # hay histórico pero no latest

    bundle_dir = tmp_path / "docs-build"
    result = build_pages_bundle(output, bundle_dir)

    # No levanta excepción; escribe un placeholder.
    assert result.index_html.exists()
    assert "Esperando primer run" in result.index_html.read_text(encoding="utf-8")
    assert result.latest_csv is None


def test_build_pages_bundle_clean_rebuild(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    _write(output / "screening_latest.html", "LATEST")

    bundle_dir = tmp_path / "docs-build"
    bundle_dir.mkdir()
    _write(bundle_dir / "basura.txt", "vieja")  # basura preexistente
    (bundle_dir / "history").mkdir()
    _write(bundle_dir / "history" / "stale.html", "stale")

    build_pages_bundle(output, bundle_dir)

    # El rebuild limpió la basura previa.
    assert not (bundle_dir / "basura.txt").exists()
    assert not (bundle_dir / "history" / "stale.html").exists()
    assert (bundle_dir / "index.html").exists()


def test_history_index_uses_relative_hrefs(tmp_path):
    """Regresión: los hrefs del history deben ser relativos al documento (sin barra inicial).

    Servido como project page bajo `/puts-screener/`, un href root-absoluto resuelve contra
    `goloop-ar.github.io/...` perdiendo el prefijo del repo y devolviendo 404. Con paths
    relativos funciona tanto en root como en subpath sin necesidad de configurar base URL.
    """
    _timestamped(tmp_path, "2026-05-22", "2200")
    entries = discover_history(tmp_path)
    html = render_history_index(entries, DEFAULT_TEMPLATE_PATH)

    # Hrefs relativos esperados (sin barra inicial):
    assert 'href="history/screening_2026-05-22_2200.html"' in html
    assert 'href="history/screening_2026-05-22_2200.csv"' in html
    assert 'href="index.html"' in html

    # Ningún href de navegación debe ser root-absoluto:
    assert 'href="/history/' not in html
    assert 'href="/index.html"' not in html

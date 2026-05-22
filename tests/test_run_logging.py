"""Test de la configuración de logging dual (consola + archivo) de run.py."""

import logging
from datetime import datetime

from puts_screener.run import _configure_logging


def test_configure_logging_creates_file_with_content(tmp_path):
    root = logging.getLogger()
    orig_handlers = root.handlers[:]
    orig_level = root.level
    try:
        log_path = _configure_logging(
            log_dir=tmp_path / "logs", timestamp=datetime(2026, 5, 21, 16, 30)
        )
        assert log_path.name == "screening_2026-05-21_1630.log"
        assert log_path.exists()

        logging.getLogger("puts_screener.logtest").info("linea de prueba de logging")

        content = log_path.read_text(encoding="utf-8")
        assert "linea de prueba de logging" in content
        assert len(content.strip().splitlines()) >= 1
    finally:
        for handler in root.handlers[:]:
            if handler not in orig_handlers:
                handler.close()
                root.removeHandler(handler)
        root.setLevel(orig_level)

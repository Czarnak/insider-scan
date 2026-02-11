"""Insider Scanner GUI entry point."""

from __future__ import annotations

import sys


def main() -> None:
    """Launch the Insider Scanner desktop application."""
    from insider_scanner.utils.config import ensure_dirs
    from insider_scanner.utils.logging import setup_logging
    from insider_scanner.core.senate import init_default_congress_file

    setup_logging()
    ensure_dirs()
    init_default_congress_file()

    from PySide6.QtWidgets import QApplication
    from insider_scanner.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Insider Scanner")
    app.setOrganizationName("InsiderScanner")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

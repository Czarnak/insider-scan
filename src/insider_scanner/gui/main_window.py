"""Main window with default OS style and scan tab."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow,
    QStatusBar,
    QTabWidget,
)


class MainWindow(QMainWindow):
    """Insider Scanner main window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Insider Scanner")
        self.setMinimumSize(900, 550)
        self.resize(1100, 650)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._init_scan_tab()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _init_scan_tab(self):
        try:
            from insider_scanner.gui.scan_tab import ScanTab
            self.scan_tab = ScanTab()
            self.tabs.addTab(self.scan_tab, "Insider Scan")
        except Exception as exc:
            from PySide6.QtWidgets import QLabel
            self.tabs.addTab(QLabel(f"Scan tab failed to load: {exc}"), "Scan")

    def log_status(self, message: str):
        self.status_bar.showMessage(message)

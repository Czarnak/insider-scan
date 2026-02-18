"""Main window with default OS style and tabbed interface."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
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

        self._init_dashboard_tab()
        self._init_scan_tab()
        self._init_congress_tab()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _init_dashboard_tab(self):
        try:
            from insider_scanner.core.dashboard import (
                DEFAULT_INDICATOR_SPECS,
                MarketProvider,
            )
            from insider_scanner.gui.dashboard_tab import DashboardTab

            self.dashboard_tab = DashboardTab(
                MarketProvider(),
                DEFAULT_INDICATOR_SPECS,
            )
            self.tabs.addTab(self.dashboard_tab, "Dashboard")
            self.dashboard_tab.refresh_async()
        except Exception as exc:
            self.tabs.addTab(
                QLabel(f"Dashboard failed to load: {exc}"),
                "Dashboard",
            )

    def _init_scan_tab(self):
        try:
            from insider_scanner.gui.scan_tab import ScanTab

            self.scan_tab = ScanTab()
            self.tabs.addTab(self.scan_tab, "Insider Scan")
        except Exception as exc:
            self.tabs.addTab(
                QLabel(f"Scan tab failed to load: {exc}"),
                "Scan",
            )

    def _init_congress_tab(self):
        try:
            from insider_scanner.gui.congress_tab import CongressTab

            self.congress_tab = CongressTab()
            self.tabs.addTab(self.congress_tab, "Congress Scan")
        except Exception as exc:
            self.tabs.addTab(
                QLabel(f"Congress tab failed to load: {exc}"),
                "Congress",
            )

    def log_status(self, message: str):
        self.status_bar.showMessage(message)

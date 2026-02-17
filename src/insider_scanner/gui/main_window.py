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

        self._init_dashboard_tab()
        self._init_scan_tab()
        self._init_congress_tab()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _init_dashboard_tab(self):
        try:
            from insider_scanner.gui.dashboard_tab import DashboardTab, IndicatorSpec
            from insider_scanner.core.dashboard import MarketProvider

            self.indicator_specs = [
                IndicatorSpec(
                    key="mvrv_z",
                    title="MVRV Z-Score",
                    bands=((-10, 0, "green"), (0, 3, "yellow"), (3, 7, "orange"), (7, 1e9, "red")),
                ),
                IndicatorSpec(
                    key="nupl",
                    title="NUPL",
                    bands=((-1, 0, "green"), (0, 0.25, "yellow"), (0.25, 0.5, "orange"), (0.5, 1.1, "red")),
                ),
                IndicatorSpec(
                    key="rsi",
                    title="RSI",
                    bands=((0, 30, "green"), (30, 40, "yellow"), (40, 70, "orange"), (70, 101, "red")),
                ),
                IndicatorSpec(
                    key="vdd",
                    title="VDD",
                    bands=((0, 1, "green"), (1, 2, "yellow"), (2, 3, "orange"), (3, 1e9, "red")),
                ),
                IndicatorSpec(
                    key="lth_rp_gap",
                    title="Price vs LTH RP",
                    unit="%",
                    bands=((-1000, -5, "green"), (-5, 5, "yellow"), (5, 1000, "orange")),
                ),
                IndicatorSpec(
                    key="cbbi",
                    title="CBBI",
                    bands=((0, 16, "green"), (16, 60, "yellow"), (60, 80, "orange"), (80, 101, "red")),
                ),
            ]
            self.provider = MarketProvider()
            self.dashboard_tab = DashboardTab(self.provider, self.indicator_specs)
            self.tabs.addTab(self.dashboard_tab, "Dashboard")
            self.dashboard_tab.refresh_async()
        except Exception as exc:
            from PySide6.QtWidgets import QLabel
            self.tabs.addTab(QLabel(f"Scan tab failed to load: {exc}"), "Dashboard")

    def _init_scan_tab(self):
        try:
            from insider_scanner.gui.scan_tab import ScanTab
            self.scan_tab = ScanTab()
            self.tabs.addTab(self.scan_tab, "Insider Scan")
        except Exception as exc:
            from PySide6.QtWidgets import QLabel
            self.tabs.addTab(QLabel(f"Scan tab failed to load: {exc}"), "Scan")

    def _init_congress_tab(self):
        try:
            from insider_scanner.gui.congress_tab import CongressTab
            self.scan_tab = CongressTab()
            self.tabs.addTab(self.scan_tab, "Congress Scan")
        except Exception as exc:
            from PySide6.QtWidgets import QLabel
            self.tabs.addTab(QLabel(f"Scan tab failed to load: {exc}"), "Congress")

    def log_status(self, message: str):
        self.status_bar.showMessage(message)

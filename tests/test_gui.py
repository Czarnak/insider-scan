"""GUI tests using pytest-qt for widget creation and basic interactions."""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt


class TestPandasTableModel:
    def test_set_dataframe(self, qtbot):
        from insider_scanner.gui.widgets import PandasTableModel
        model = PandasTableModel()
        df = pd.DataFrame({"ticker": ["AAPL", "MSFT"], "value": [1000.0, 2000.0]})
        model.set_dataframe(df)
        assert model.rowCount() == 2
        assert model.columnCount() == 2

    def test_data_formatting(self, qtbot):
        from insider_scanner.gui.widgets import PandasTableModel
        model = PandasTableModel()
        df = pd.DataFrame({"val": [1234567.89]})
        model.set_dataframe(df)
        idx = model.index(0, 0)
        assert model.data(idx) == "1,234,567.89"

    def test_empty(self, qtbot):
        from insider_scanner.gui.widgets import PandasTableModel
        model = PandasTableModel()
        assert model.rowCount() == 0


class TestSortableTableModel:
    def test_set_and_sort(self, qtbot):
        from insider_scanner.gui.widgets import SortableTableModel
        model = SortableTableModel()
        df = pd.DataFrame({"name": ["B", "A", "C"], "val": [2, 1, 3]})
        model.set_dataframe(df)
        assert model.rowCount() == 3
        model.sort(1, Qt.SortOrder.AscendingOrder)
        assert model.rowCount() == 3


class TestScanTab:
    def test_create(self, qtbot):
        from insider_scanner.gui.scan_tab import ScanTab
        tab = ScanTab()
        qtbot.addWidget(tab)
        assert tab.btn_scan is not None
        assert tab.btn_latest is not None
        assert tab.ticker_edit is not None

    def test_empty_ticker_warning(self, qtbot):
        from insider_scanner.gui.scan_tab import ScanTab
        tab = ScanTab()
        qtbot.addWidget(tab)
        # Ticker is empty, scan should not crash
        tab.ticker_edit.setText("")
        # _run_scan shows a warning but doesn't crash

    def test_date_widgets_exist(self, qtbot):
        from insider_scanner.gui.scan_tab import ScanTab
        tab = ScanTab()
        qtbot.addWidget(tab)
        assert tab.start_date is not None
        assert tab.end_date is not None
        assert tab.chk_use_dates is not None

    def test_date_toggle_enables_fields(self, qtbot):
        from insider_scanner.gui.scan_tab import ScanTab
        tab = ScanTab()
        qtbot.addWidget(tab)
        # Initially disabled
        assert not tab.start_date.isEnabled()
        assert not tab.end_date.isEnabled()
        # Enable
        tab.chk_use_dates.setChecked(True)
        assert tab.start_date.isEnabled()
        assert tab.end_date.isEnabled()
        # Disable again
        tab.chk_use_dates.setChecked(False)
        assert not tab.start_date.isEnabled()
        assert not tab.end_date.isEnabled()

    def test_get_dates_disabled(self, qtbot):
        from insider_scanner.gui.scan_tab import ScanTab
        tab = ScanTab()
        qtbot.addWidget(tab)
        # When dates unchecked, helpers return None
        assert tab._get_start_date() is None
        assert tab._get_end_date() is None

    def test_get_dates_enabled(self, qtbot):
        from datetime import date
        from PySide6.QtCore import QDate
        from insider_scanner.gui.scan_tab import ScanTab
        tab = ScanTab()
        qtbot.addWidget(tab)
        tab.chk_use_dates.setChecked(True)
        tab.start_date.setDate(QDate(2025, 3, 15))
        tab.end_date.setDate(QDate(2025, 9, 30))
        assert tab._get_start_date() == date(2025, 3, 15)
        assert tab._get_end_date() == date(2025, 9, 30)


class TestMainWindow:
    def test_create(self, qtbot):
        from insider_scanner.gui.main_window import MainWindow
        win = MainWindow()
        qtbot.addWidget(win)
        assert win.tabs.count() == 1

    def test_tab_name(self, qtbot):
        from insider_scanner.gui.main_window import MainWindow
        win = MainWindow()
        qtbot.addWidget(win)
        assert win.tabs.tabText(0) == "Insider Scan"

    def test_status_bar(self, qtbot):
        from insider_scanner.gui.main_window import MainWindow
        win = MainWindow()
        qtbot.addWidget(win)
        win.log_status("Testing")
        assert win.status_bar.currentMessage() == "Testing"

"""Dashboard tab: market prices, VIX chart, Fear & Greed, indicators.

All data is fetched by a SINGLE background Worker calling
``provider.fetch_all()``.  This avoids yfinance thread-safety issues
(concurrent yf.download calls corrupt each other's data).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QThreadPool, Slot, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from insider_scanner.core.dashboard import (
    PRICE_SYMBOLS,
    DashboardSnapshot,
    IndicatorSpec,
    MarketDataProvider,
)
from insider_scanner.gui.widgets import (
    PriceChangeCard,
    ValueCard,
    fg_color,
    indicator_color,
)
from insider_scanner.utils.threading import Worker

log = logging.getLogger(__name__)


class DashboardTab(QWidget):
    """Live-updating dashboard with prices, VIX chart, F&G, and indicators."""

    def __init__(
        self,
        provider: MarketDataProvider,
        indicator_specs: List[IndicatorSpec],
        parent=None,
    ):
        super().__init__(parent)
        self.provider = provider
        self.indicator_specs = indicator_specs

        # Single-worker guard
        self._refreshing: bool = False
        self._refresh_queued: bool = False

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # 1) Top row: price cards
        top = QHBoxLayout()
        top.setSpacing(10)

        self.top_cards: Dict[str, PriceChangeCard] = {
            sym: PriceChangeCard(label)
            for sym, label in zip(
                PRICE_SYMBOLS,
                ["Gold", "Silver", "Crude Oil", "S&P 500", "Nasdaq"],
            )
        }
        for card in self.top_cards.values():
            top.addWidget(card, 1)
        root.addLayout(top)

        # 2) VIX chart
        axis = pg.DateAxisItem(orientation="bottom")
        self.vix_plot = pg.PlotWidget(axisItems={"bottom": axis})
        self.vix_plot.setBackground("#1e1e1e")
        self.vix_plot.showGrid(x=True, y=True, alpha=0.35)
        self.vix_plot.setMinimumHeight(220)
        self.vix_plot.setTitle(
            "VIX (last ~30 days)", color="w", size="11pt",
        )

        for axis_name in ("left", "bottom"):
            ax = self.vix_plot.getAxis(axis_name)
            ax.setPen(pg.mkPen(color="w", width=1))
            ax.setTextPen(pg.mkPen(color="w"))

        self.vix_curve = self.vix_plot.plot(
            pen=pg.mkPen(color="#00bcd4", width=2),
        )
        root.addWidget(self.vix_plot)

        # 3) Bottom: Fear & Greed (left) + Indicator tiles (right)
        split = QHBoxLayout()
        split.setSpacing(10)

        # Left: Fear & Greed cards
        left_box = QVBoxLayout()
        left_box.setSpacing(10)
        self.fg_cards: Dict[str, ValueCard] = {
            "stocks": ValueCard("Fear & Greed (Stocks)"),
            "gold": ValueCard("Fear & Greed (Gold)"),
            "crypto": ValueCard("Fear & Greed (Crypto)"),
        }
        for c in self.fg_cards.values():
            left_box.addWidget(c)
        left_box.addStretch(1)

        left_widget = QWidget()
        left_widget.setLayout(left_box)

        # Right: Indicator tiles in a 2-column grid
        right_grid = QGridLayout()
        right_grid.setHorizontalSpacing(10)
        right_grid.setVerticalSpacing(10)
        self.ind_cards: Dict[str, ValueCard] = {}
        cols = 2
        for i, spec in enumerate(self.indicator_specs):
            card = ValueCard(spec.title)
            self.ind_cards[spec.key] = card
            r, c = divmod(i, cols)
            right_grid.addWidget(card, r, c)

        right_widget = QWidget()
        right_widget.setLayout(right_grid)

        split.addWidget(left_widget, 1)
        split.addWidget(right_widget, 1)
        root.addLayout(split)

        # Auto-refresh timer
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.refresh_async)
        self._timer.start()

    # ------------------------------------------------------------------
    # Single-worker refresh (no race conditions)
    # ------------------------------------------------------------------

    @Slot()
    def refresh_async(self):
        """Request a dashboard refresh.

        If a refresh is already running, the request is queued and
        executes when the current one finishes.  Only ONE worker runs
        at a time, which avoids yfinance thread-safety issues.
        """
        if self._refreshing:
            self._refresh_queued = True
            log.debug("Refresh queued (previous still running)")
            return
        self._start_refresh()

    def _start_refresh(self):
        """Launch the single background worker."""
        self._refreshing = True
        self._refresh_queued = False

        worker = Worker(self.provider.fetch_all)
        worker.signals.result.connect(self._on_snapshot)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(self._on_finished)
        QThreadPool.globalInstance().start(worker)

    @Slot()
    def _on_finished(self):
        """Worker done — run queued refresh if one was requested."""
        self._refreshing = False
        if self._refresh_queued:
            self._refresh_queued = False
            self._start_refresh()

    @Slot(object)
    def _on_snapshot(self, snapshot: object):
        """Apply all data from a single DashboardSnapshot."""
        if not isinstance(snapshot, DashboardSnapshot):
            return

        # Prices
        for symbol, card in self.top_cards.items():
            s = snapshot.prices.get(symbol, pd.Series(dtype=float))
            self._apply_price(card, s)

        # VIX chart
        self._apply_vix(snapshot.vix)

        # Fear & Greed
        self._apply_fg(snapshot.fear_greed)

        # Indicators
        self._apply_indicators(snapshot.indicators)

    @Slot(tuple)
    def _on_error(self, exc_info: tuple):
        exc_type, exc_value, _ = exc_info
        log.warning(
            "Dashboard refresh failed: %s: %s", exc_type.__name__, exc_value,
        )
        # Set all cards to n/a
        for card in self.top_cards.values():
            card.set_value(None, None, self._NA_BG)
        self.vix_curve.setData([], [])
        for card in self.fg_cards.values():
            card.set_value("n/a", "data unavailable", self._NA_BG)
        for spec in self.indicator_specs:
            self.ind_cards[spec.key].set_value(
                "n/a", "data unavailable", self._NA_BG,
            )

    # ------------------------------------------------------------------
    # Apply helpers
    # ------------------------------------------------------------------

    _NA_BG = (80, 80, 80, 120)

    def _apply_price(self, card: PriceChangeCard, s: pd.Series):
        if s is None or len(s) < 2:
            card.set_value(None, None, self._NA_BG)
            return

        last = float(s.iloc[-1])
        prev = float(s.iloc[-2])
        pct = (last / prev - 1.0) * 100.0
        bg = (60, 160, 80, 160) if pct >= 0 else (180, 40, 40, 160)
        card.set_value(last, pct, bg)

    def _apply_vix(self, s: pd.Series):
        if s is None or s.empty:
            self.vix_curve.setData([], [])
            return

        # Convert tz-aware DatetimeIndex → POSIX seconds (float64).
        # Using .astype("int64") is safer than .view("int64") across
        # pandas versions and timezone-aware indices.
        try:
            x = s.index.astype("int64").to_numpy(dtype=np.float64) / 1e9
        except (TypeError, AttributeError):
            # Fallback for unusual index types
            x = np.array(
                [ts.timestamp() for ts in s.index], dtype=np.float64,
            )
        y = s.to_numpy(dtype=np.float64)

        self.vix_curve.setData(x, y)
        self.vix_plot.getPlotItem().vb.autoRange()

    def _apply_fg(self, fg: dict):
        for k, card in self.fg_cards.items():
            val = fg.get(k)
            if not val:
                card.set_value("n/a", "data unavailable", self._NA_BG)
                continue
            value, label = val
            card.set_value(str(int(value)), str(label), fg_color(int(value)))

    def _apply_indicators(self, values: dict):
        for spec in self.indicator_specs:
            card = self.ind_cards[spec.key]
            v = values.get(spec.key)
            if v is None:
                card.set_value("n/a", "data unavailable", self._NA_BG)
                continue
            color = indicator_color(float(v), spec.bands)
            suffix = f" {spec.unit}".rstrip()
            card.set_value(f"{v}{suffix}", "", color)

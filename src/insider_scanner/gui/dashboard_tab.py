"""Dashboard tab: main market and crypto indicators."""

from __future__ import annotations

from typing import Dict, List, Callable, Any

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QThreadPool, Slot, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QGridLayout,
)

from insider_scanner.core.dashboard import MarketDataProvider, IndicatorSpec
from insider_scanner.gui.widgets import ValueCard, indicator_color, fg_color, PriceChangeCard
from insider_scanner.utils.threading import Worker


class DashboardTab(QWidget):
    def __init__(self, provider: MarketDataProvider, indicator_specs: List[IndicatorSpec], parent=None):
        super().__init__(parent)
        self.provider = provider
        self.indicator_specs = indicator_specs

        self.pool = QThreadPool.globalInstance()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # 1) Top row: price + Δ1D%
        top = QHBoxLayout()
        top.setSpacing(10)

        self.top_cards: Dict[str, PriceChangeCard] = {
            "GC=F": PriceChangeCard("Gold"),
            "SI=F": PriceChangeCard("Silver"),
            "CL=F": PriceChangeCard("Crude Oil"),
            "ES=F": PriceChangeCard("S&P 500"),
            "NQ=F": PriceChangeCard("Nasdaq"),
        }
        for card in self.top_cards.values():
            top.addWidget(card, 1)
        root.addLayout(top)

        # 2) VIX plot
        axis = pg.DateAxisItem(orientation="bottom")
        self.vix_plot = pg.PlotWidget()
        self.vix_plot = pg.PlotWidget(axisItems={"bottom": axis})
        self.vix_plot.setBackground(None)
        self.vix_plot.showGrid(x=True, y=True, alpha=0.35)
        self.vix_plot.setMinimumHeight(220)
        self.vix_plot.setTitle("VIX (last ~30 days)")
        self.vix_curve = self.vix_plot.plot(pen=pg.mkPen(width=3))
        root.addWidget(self.vix_plot)

        # 3) Bottom split
        split = QHBoxLayout()
        split.setSpacing(10)

        # Left: Fear & Greed
        left_box = QVBoxLayout()
        left_box.setSpacing(10)

        self.fg_cards = {
            "stocks": ValueCard("Fear & Greed (Stocks)"),
            "gold": ValueCard("Fear & Greed (Gold)"),
            "crypto": ValueCard("Fear & Greed (Crypto)"),
        }
        for c in self.fg_cards.values():
            left_box.addWidget(c)
        left_box.addStretch(1)

        left_widget = QWidget()
        left_widget.setLayout(left_box)

        # Right: Indicator tiles
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

        # Timer refresh
        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self.refresh_async)
        self.timer.start()

    def _submit(self, key: str, fn: Callable[[], Any]):
        def work() -> tuple[str, Any]:
            return key, fn()

        worker = Worker(work)
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(lambda exc_info, k=key: self._on_failed(k, exc_info))
        QThreadPool.globalInstance().start(worker)

    @Slot()
    def refresh_async(self):
        # top prices
        for symbol in self.top_cards.keys():
            self._submit(f"price:{symbol}", lambda s=symbol: self.provider.get_daily_close(s, 10))

        # VIX
        self._submit("vix", lambda: self.provider.get_vix_intraday_or_daily(45))

        # fear & greed
        self._submit("fg", lambda: self.provider.get_fear_greed())

        # indicators (read is local, no need threads; but keep consistent)
        self._submit("indicators", lambda: getattr(self.provider, "latest_indicator_values", {}))

    @Slot(object)
    def _on_result(self, payload: object):
        key, result = payload  # payload is (key, result)

        if key.startswith("price:"):
            symbol = key.split(":", 1)[1]
            self._apply_price(symbol, result)  # type: ignore[arg-type]
            return

        if key == "vix":
            self._apply_vix(result)  # type: ignore[arg-type]
            return

        if key == "fg":
            self._apply_fg(result)  # type: ignore[arg-type]
            return

        if key == "indicators":
            self._apply_indicators(result)  # type: ignore[arg-type]
            return

    def _on_failed(self, key: str, exc_info: tuple):
        exc_type, exc_value, _ = exc_info
        error = f"{exc_type.__name__}: {exc_value}"
        print(f"[Dashboard] Worker failed: {key} -> {error}")

        # set "n/a" gracefully
        if key.startswith("price:"):
            symbol = key.split(":", 1)[1]
            self._set_price_na(symbol)
        elif key == "vix":
            self.vix_curve.setData([])
        elif key == "fg":
            for card in self.fg_cards.values():
                card.set_value("n/a", "data unavailable", (80, 80, 80, 120))
        elif key == "indicators":
            for spec in self.indicator_specs:
                self.ind_cards[spec.key].set_value("n/a", "data unavailable", (80, 80, 80, 120))

    def _set_price_na(self, symbol: str):
        card = self.top_cards[symbol]
        card.set_value(None, None, (80, 80, 80, 120))

    def _apply_price(self, symbol: str, series_obj: object):
        card = self.top_cards[symbol]
        s = series_obj if isinstance(series_obj, pd.Series) else pd.Series(dtype=float)
        if s is None or len(s) < 2:
            card.set_value(None, None, (80, 80, 80, 120))
            return

        last = float(s.iloc[-1])
        prev = float(s.iloc[-2])
        pct = (last / prev - 1.0) * 100.0
        bg = (60, 160, 80, 160) if pct >= 0 else (180, 40, 40, 160)
        card.set_value(last, pct, bg)

    def _apply_vix(self, series_obj: object):
        s = series_obj if isinstance(series_obj, pd.Series) else pd.Series(dtype=float)
        if s is None or s.empty:
            self.vix_curve.setData([])
            return
        x = (s.index.view("int64") // 10 ** 9).to_numpy(dtype=np.int64)
        y = s.to_numpy(dtype=float)

        self.vix_curve.setData(x, y)
        self.vix_plot.getPlotItem().vb.autoRange()

    def _apply_fg(self, fg_obj: object):
        fg = fg_obj if isinstance(fg_obj, dict) else {}
        for k, card in self.fg_cards.items():
            val = fg.get(k)
            if not val:
                card.set_value("n/a", "data unavailable", (80, 80, 80, 120))
                continue
            value, label = val
            card.set_value(str(int(value)), str(label), fg_color(int(value)))

    def _apply_indicators(self, ind_obj: object):
        values = ind_obj if isinstance(ind_obj, dict) else {}
        for spec in self.indicator_specs:
            card = self.ind_cards[spec.key]
            v = values.get(spec.key)
            if v is None:
                card.set_value("n/a", "data unavailable", (80, 80, 80, 120))
                continue
            color = indicator_color(float(v), spec.bands)
            suffix = f" {spec.unit}".rstrip()
            card.set_value(f"{v}{suffix}", "", color)

"""Reusable GUI widgets: pandas table model."""

from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import (
    Qt,
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
)


class PandasTableModel(QAbstractTableModel):
    """Qt table model backed by a pandas DataFrame."""

    def __init__(self, df: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()

    def set_dataframe(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df.reset_index(drop=True)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return len(self._df.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            val = self._df.iloc[index.row(), index.column()]
            if isinstance(val, float):
                return f"{val:,.2f}"
            return str(val)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        # Highlight congress trades
        if role == Qt.ItemDataRole.ForegroundRole:
            if "is_congress" in self._df.columns:
                if self._df.iloc[index.row()]["is_congress"]:
                    from PySide6.QtGui import QColor
                    return QColor(200, 50, 50)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    @property
    def dataframe(self):
        return self._df


class SortableTableModel(QSortFilterProxyModel):
    """Proxy adding sort/filter on top of PandasTableModel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = PandasTableModel(parent=self)
        self.setSourceModel(self._source)
        self.setDynamicSortFilter(True)

    def set_dataframe(self, df: pd.DataFrame):
        self._source.set_dataframe(df)

    @property
    def dataframe(self):
        return self._source.dataframe

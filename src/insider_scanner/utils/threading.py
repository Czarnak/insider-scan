"""Threading helper for background tasks in the GUI."""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(tuple)
    finished = Signal()


class Worker(QRunnable):
    """Run a callable in a background thread."""

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception:
            self.signals.error.emit(sys.exc_info())
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()

"""Reusable QThread boundary for blocking synchronization operations."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot


class OperationWorker(QObject):
    """Run a callable without retaining or touching any widget."""

    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, callback: Callable[[], object]) -> None:
        super().__init__()
        self._callback = callback

    @Slot()
    def run(self) -> None:
        try:
            result = self._callback()
        except Exception:  # unexpected details must not cross the UI boundary
            self.failed.emit("La operación no pudo completarse de forma segura.")
        else:
            self.succeeded.emit(result)
        finally:
            self.finished.emit()


class AsyncOperation(QObject):
    """Own one worker/thread pair and reject overlapping starts."""

    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: OperationWorker | None = None

    @property
    def active(self) -> bool:
        return self._thread is not None

    def start(self, callback: Callable[[], object]) -> bool:
        if self.active:
            return False
        thread = QThread()
        worker = OperationWorker(callback)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self.succeeded)
        worker.failed.connect(self.failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup)
        self._thread = thread
        self._worker = worker
        thread.start()
        return True

    @Slot()
    def _cleanup(self) -> None:
        self._thread = None
        self._worker = None
        self.finished.emit()

"""A capture pinned over every window - a reference that stays put
(Snipaste / PixPin). Drag to move, wheel to zoom, Ctrl+wheel for
opacity, double click or Esc to close, right click for the rest."""
import datetime
import os

from PySide6 import QtCore, QtGui, QtWidgets

from . import store, theme
from .keys import latin


class PinWindow(QtWidgets.QWidget):
    def __init__(self, pixmap: QtGui.QPixmap, top_left: QtCore.QPoint):
        super().__init__(None, QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.WindowStaysOnTopHint
                         | QtCore.Qt.WindowType.Tool)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.pixmap = pixmap
        self.scale = 1.0
        self._drag = None
        self.setWindowOpacity(1.0)
        self._resize()
        self.move(top_left)
        self.show()

    def _resize(self) -> None:
        dpr = self.pixmap.devicePixelRatio() or 1.0
        screen = QtGui.QGuiApplication.primaryScreen().devicePixelRatio()
        w = self.pixmap.width() / screen * self.scale
        h = self.pixmap.height() / screen * self.scale
        self.resize(max(24, int(w)), max(24, int(h)))

    def paintEvent(self, _e):                                    # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(self.rect(), self.pixmap, QtCore.QRectF(self.pixmap.rect()).toRect())
        p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def mousePressEvent(self, e):                                # noqa: N802
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):                                 # noqa: N802
        if self._drag is not None and e.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):                             # noqa: N802
        self._drag = None

    def mouseDoubleClickEvent(self, _e):                         # noqa: N802
        self.close()

    def wheelEvent(self, e):                                     # noqa: N802
        up = e.angleDelta().y() > 0
        if e.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            self.setWindowOpacity(max(0.15, min(1.0, self.windowOpacity() + (0.08 if up else -0.08))))
            return
        center = self.geometry().center()
        self.scale = max(0.1, min(8.0, self.scale * (1.1 if up else 1 / 1.1)))
        self._resize()
        self.move(center - QtCore.QPoint(self.width() // 2, self.height() // 2))

    def keyPressEvent(self, e):                                  # noqa: N802
        if e.key() == QtCore.Qt.Key.Key_Escape:
            self.close()
        elif e.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier and latin(e) == QtCore.Qt.Key.Key_C:
            QtWidgets.QApplication.clipboard().setPixmap(self.pixmap)

    def contextMenuEvent(self, e):                               # noqa: N802
        menu = QtWidgets.QMenu(self)
        menu.addAction(theme.icon("copy"), "Copy", lambda: QtWidgets.QApplication.clipboard().setPixmap(self.pixmap))
        menu.addAction(theme.icon("floppy-disk"), "Save", self._save)
        menu.addAction(theme.icon("frame-corners"), "Original Size", self._reset)
        sub = menu.addMenu("Opacity")
        for value in (100, 80, 60, 40):
            sub.addAction(f"{value}%", lambda v=value: self.setWindowOpacity(v / 100))
        menu.addSeparator()
        menu.addAction(theme.icon("x"), "Close  (Esc / double click)", self.close)
        menu.exec(e.globalPos())

    def _reset(self) -> None:
        self.scale = 1.0
        self._resize()

    def _save(self) -> None:
        path = os.path.join(store.save_dir(), datetime.datetime.now().strftime("LeadTool_%Y-%m-%d_%H-%M-%S.png"))
        self.pixmap.save(path)

"""A small colour picker that opens beside the button - never Windows' big
dialog. Saturation/value square, hue strip, HEX,
the quick swatches; changes apply live."""
from PySide6 import QtCore, QtGui, QtWidgets

from . import store, theme


class _Bar(QtWidgets.QWidget):
    """One HSV channel as a slider: its own gradient, a handle, drag it."""
    changed = QtCore.Signal()

    def __init__(self, parent, channel: str):
        super().__init__(parent)
        self.channel = channel                         # "h" / "s" / "v"
        self.setFixedHeight(14)
        self.value = 0.0
        self.picker = parent

    def paintEvent(self, _e):                                    # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        r = QtCore.QRectF(self.rect()).adjusted(0, 3, 0, -3)
        h, s, v = self.picker.hue.h, self.picker.sv.s, self.picker.sv.v
        g = QtGui.QLinearGradient(r.left(), 0, r.right(), 0)
        for i in range(7 if self.channel == "h" else 2):
            t = i / (6 if self.channel == "h" else 1)
            hsv = {"h": (t % 1.0, max(s, 0.25), max(v, 0.35)), "s": (h, t, v), "v": (h, s, t)}[self.channel]
            g.setColorAt(t, QtGui.QColor.fromHsvF(*hsv))
        p.setPen(QtGui.QPen(QtGui.QColor("#1f1f1f"), 1))
        p.setBrush(g)
        p.drawRoundedRect(r, 3, 3)
        x = r.left() + self.value * r.width()
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 3))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(x - 3, 0.5, 6, self.height() - 1), 2, 2)
        p.setPen(QtGui.QPen(QtGui.QColor("#fff"), 1.5))
        p.drawRoundedRect(QtCore.QRectF(x - 3, 0.5, 6, self.height() - 1), 2, 2)

    def mousePressEvent(self, e):                                # noqa: N802
        self._set(e.position())

    def mouseMoveEvent(self, e):                                 # noqa: N802
        self._set(e.position())

    def _set(self, pos):
        self.value = min(0.999 if self.channel == "h" else 1.0, max(0.0, pos.x() / max(1, self.width())))
        self.update()
        self.changed.emit()


class _SV(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(180, 140)
        self.h, self.s, self.v = 0.0, 1.0, 1.0

    def paintEvent(self, _e):                                    # noqa: N802
        p = QtGui.QPainter(self)
        r = QtCore.QRectF(self.rect())
        p.fillRect(r, QtGui.QColor.fromHsvF(self.h, 1, 1))
        g = QtGui.QLinearGradient(0, 0, r.width(), 0)
        g.setColorAt(0, QtGui.QColor(255, 255, 255))
        g.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.fillRect(r, g)
        g = QtGui.QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0, QtGui.QColor(0, 0, 0, 0))
        g.setColorAt(1, QtGui.QColor(0, 0, 0))
        p.fillRect(r, g)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        c = QtCore.QPointF(self.s * r.width(), (1 - self.v) * r.height())
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 3))
        p.drawEllipse(c, 5, 5)
        p.setPen(QtGui.QPen(QtGui.QColor("#fff"), 1.5))
        p.drawEllipse(c, 5, 5)

    def mousePressEvent(self, e):                                # noqa: N802
        self._set(e.position())

    def mouseMoveEvent(self, e):                                 # noqa: N802
        self._set(e.position())

    def _set(self, pos):
        self.s = min(1, max(0, pos.x() / self.width()))
        self.v = min(1, max(0, 1 - pos.y() / self.height()))
        self.update()
        self.changed.emit()


class _Hue(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(16, 140)
        self.h = 0.0

    def paintEvent(self, _e):                                    # noqa: N802
        p = QtGui.QPainter(self)
        g = QtGui.QLinearGradient(0, 0, 0, self.height())
        for i in range(7):
            g.setColorAt(i / 6, QtGui.QColor.fromHsvF((i / 6) % 1.0, 1, 1))
        p.fillRect(self.rect(), g)
        y = self.h * self.height()
        p.setPen(QtGui.QPen(QtGui.QColor("#fff"), 2))
        p.drawRect(QtCore.QRectF(1, y - 2, self.width() - 2, 4))

    def mousePressEvent(self, e):                                # noqa: N802
        self._set(e.position())

    def mouseMoveEvent(self, e):                                 # noqa: N802
        self._set(e.position())

    def _set(self, pos):
        self.h = min(0.999, max(0, pos.y() / self.height()))
        self.update()
        self.changed.emit()


class ColorPicker(QtWidgets.QWidget):
    """Popup. picked(QColor) on every change."""
    picked = QtCore.Signal(QtGui.QColor)

    def __init__(self, parent, color: QtGui.QColor):
        super().__init__(parent, QtCore.Qt.WindowType.Popup | QtCore.Qt.WindowType.FramelessWindowHint)
        self.setObjectName("ltPicker")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#ltPicker { background: #333333; border: 1px solid #4a4a4a; }")
        col = QtWidgets.QVBoxLayout(self)
        col.setContentsMargins(8, 6, 8, 8)
        col.setSpacing(6)
        head = QtWidgets.QHBoxLayout()
        head.addStretch(1)
        self.pin_btn = QtWidgets.QToolButton()
        self.pin_btn.setIcon(theme.icon("push-pin", 14))
        self.pin_btn.setCheckable(True)
        self.pin_btn.setFixedSize(22, 22)
        self.pin_btn.setToolTip("Pin: the palette stays on screen")
        self.pin_btn.toggled.connect(self.set_pinned)
        head.addWidget(self.pin_btn)
        col.addLayout(head)
        self.pinned = False
        self._grab_at = None
        row = QtWidgets.QHBoxLayout()
        self.sv, self.hue = _SV(self), _Hue(self)
        row.addWidget(self.sv)
        row.addWidget(self.hue)
        col.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.swatch = QtWidgets.QLabel()
        self.swatch.setFixedSize(28, 22)
        row.addWidget(self.swatch)
        self.hex = QtWidgets.QLineEdit()
        self.hex.setFixedWidth(90)
        self.hex.editingFinished.connect(self._from_hex)
        row.addWidget(self.hex)
        row.addStretch(1)
        col.addLayout(row)
        grid = QtWidgets.QHBoxLayout()
        grid.setSpacing(3)
        for name in store.get("colors"):
            b = QtWidgets.QToolButton()
            b.setFixedSize(18, 18)
            b.setStyleSheet(f"QToolButton {{ background: {name}; border: 1px solid #1f1f1f; border-radius: 3px; }}")
            b.clicked.connect(lambda _c=False, n=name: self.set_color(QtGui.QColor(n), emit=True))
            grid.addWidget(b)
        col.addLayout(grid)
        self.bars = {}
        for ch, label in (("h", "H"), ("s", "S"), ("v", "V")):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(6)
            name = QtWidgets.QLabel(label)
            name.setFixedWidth(10)
            name.setStyleSheet("color: #9a9a9a;")
            bar = _Bar(self, ch)
            bar.changed.connect(self._from_bars)
            num = QtWidgets.QLabel()
            num.setFixedWidth(30)
            num.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            num.setStyleSheet("color: #cfcfcf;")
            row.addWidget(name)
            row.addWidget(bar, 1)
            row.addWidget(num)
            col.addLayout(row)
            self.bars[ch] = (bar, num)
        self.sv.changed.connect(self._from_sv)
        self.hue.changed.connect(self._from_sv)
        self.set_color(color)

    def set_pinned(self, on: bool) -> None:
        """Pinned: an ordinary small window on top - it stays while you draw,
        drag it by its top edge; the picture's eyedropper updates it."""
        self.pinned = on
        pos = self.pos()
        flags = QtCore.Qt.WindowType.FramelessWindowHint
        flags |= (QtCore.Qt.WindowType.Tool | QtCore.Qt.WindowType.WindowStaysOnTopHint) if on \
            else QtCore.Qt.WindowType.Popup
        self.setWindowFlags(flags)
        self.move(pos)
        self.show()
        o = self.parent()
        if on:
            old = getattr(o, "pinned_picker", None)
            if old is not None and old is not self:
                old.close()
            o.pinned_picker = self
        elif getattr(o, "pinned_picker", None) is self:
            o.pinned_picker = None

    def closeEvent(self, e):                                     # noqa: N802
        o = self.parent()
        if getattr(o, "pinned_picker", None) is self:
            o.pinned_picker = None
        super().closeEvent(e)

    def mousePressEvent(self, e):                                # noqa: N802
        if self.pinned and e.position().y() < 28:             # the top edge moves it
            self._grab_at = e.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):                                 # noqa: N802
        if self._grab_at is not None:
            self.move(e.globalPosition().toPoint() - self._grab_at)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):                              # noqa: N802
        self._grab_at = None
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):                                  # noqa: N802
        """Space or Enter: this colour on the brush (palette closed unless pinned)."""
        if e.key() in (QtCore.Qt.Key.Key_Space, QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self.picked.emit(QtGui.QColor(self.hex.text()))
            if not self.pinned:
                self.close()
            return
        if self.pinned and e.key() == QtCore.Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    def set_color(self, color: QtGui.QColor, emit: bool = False) -> None:
        h, s, v, _a = color.getHsvF()
        self.hue.h = self.sv.h = max(0.0, h)
        self.sv.s, self.sv.v = s, v
        self.sv.update()
        self.hue.update()
        self._show(color)
        if emit:
            self.picked.emit(color)

    def _from_sv(self):
        self.sv.h = self.hue.h
        self.sv.update()
        color = QtGui.QColor.fromHsvF(self.hue.h, self.sv.s, self.sv.v)
        self._show(color)
        self.picked.emit(color)

    def _from_bars(self):
        self.hue.h = self.sv.h = self.bars["h"][0].value
        self.sv.s, self.sv.v = self.bars["s"][0].value, self.bars["v"][0].value
        self.hue.update()
        self._from_sv()

    def _from_hex(self):
        color = QtGui.QColor(self.hex.text().strip() if self.hex.text().startswith("#") else "#" + self.hex.text().strip())
        if color.isValid():
            self.set_color(color, emit=True)

    def _show(self, color):
        if getattr(self, "bars", None):
            for ch, value, top in (("h", self.hue.h, 360), ("s", self.sv.s, 100), ("v", self.sv.v, 100)):
                bar, num = self.bars[ch]
                bar.value = value
                bar.update()
                num.setText(f"{value * top:.0f}")
        self.swatch.setStyleSheet(f"background: {color.name()}; border: 1px solid #1f1f1f; border-radius: 3px;")
        self.hex.setText(color.name().upper())

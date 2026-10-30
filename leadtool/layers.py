"""Layers for a capture - Photoshop's idea cut down to what a quick feedback
paint-over needs: the screenshot at the bottom, layers of marks above it
(eye, opacity, blend mode), and ADJUSTMENT layers - Levels, Brightness /
Contrast, Hue / Saturation - that change everything below them, as in
Photoshop."""
import copy

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import store, theme

BG = "bg"
CM = QtGui.QPainter.CompositionMode
BLENDS = {"Normal": CM.CompositionMode_SourceOver, "Multiply": CM.CompositionMode_Multiply,
          "Screen": CM.CompositionMode_Screen, "Overlay": CM.CompositionMode_Overlay,
          "Soft Light": CM.CompositionMode_SoftLight, "Hard Light": CM.CompositionMode_HardLight,
          "Darken": CM.CompositionMode_Darken, "Lighten": CM.CompositionMode_Lighten,
          "Color Dodge": CM.CompositionMode_ColorDodge, "Color Burn": CM.CompositionMode_ColorBurn,
          "Difference": CM.CompositionMode_Difference}
#: key, label, low, high, neutral
ADJUST = (("brightness", "Brightness", -100, 100, 0), ("contrast", "Contrast", -100, 100, 0),
          ("black", "Levels  black", 0, 254, 0), ("gamma", "Levels  mid", 10, 300, 100),
          ("white", "Levels  white", 1, 255, 255), ("hue", "Hue", -180, 180, 0),
          ("saturation", "Saturation", -100, 100, 0))
NEUTRAL = {k: n for k, _l, _a, _b, n in ADJUST}


#: the adjustment layers: kind -> (name, the sliders it shows)
KINDS = {"levels": ("Levels", ("black", "gamma", "white")),
         "bc": ("Brightness / Contrast", ("brightness", "contrast")),
         "hsl": ("Hue / Saturation", ("hue", "saturation"))}


def new_layer(lid: str, name: str, kind: str = "") -> dict:
    """kind "" = a layer of marks; levels / bc / hsl = an adjustment layer."""
    return {"id": lid, "name": name, "visible": True, "opacity": 1.0, "blend": "Normal", "adj": dict(NEUTRAL),
            "kind": kind}


def default_layers() -> list:
    bg = new_layer(BG, "Screenshot")
    return [bg, new_layer("l1", "Layer 1")]


def neutral(adj: dict) -> bool:
    return all(adj.get(k, n) == n for k, n in NEUTRAL.items())


def adjust(image: QtGui.QImage, adj: dict) -> QtGui.QImage:
    """Levels -> brightness / contrast -> hue / saturation, on straight colour."""
    if neutral(adj):
        return image
    src = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
    w, h = src.width(), src.height()
    a = np.frombuffer(src.constBits(), np.uint8, src.sizeInBytes()).reshape(h, src.bytesPerLine())[:, :w * 4]
    a = a.reshape(h, w, 4)
    # levels, brightness, contrast: per channel -> one 256-entry table, applied by indexing (fast)
    x = np.arange(256, dtype=np.float32) / 255.0
    black, white = adj.get("black", 0) / 255.0, adj.get("white", 255) / 255.0
    x = np.clip((x - black) / max(1e-3, white - black), 0, 1)
    gamma = adj.get("gamma", 100) / 100.0
    if gamma != 1.0:
        x = x ** (1.0 / gamma)
    c = adj.get("contrast", 0) / 100.0
    x = (x - 0.5) * (1 + c if c <= 0 else 1 / max(0.05, 1 - c)) + 0.5 + adj.get("brightness", 0) / 200.0
    lut = np.clip(x * 255 + 0.5, 0, 255).astype(np.uint8)
    rgb8 = lut[a[..., :3]]
    hue, sat = adj.get("hue", 0), adj.get("saturation", 0) / 100.0
    if hue or sat:                                       # colour: one 3x3 matrix (hue turn + saturation)
        m = np.eye(3, dtype=np.float32)
        if hue:                                          # turn the colour round the grey axis (YIQ)
            t = np.radians(hue)
            yiq = np.array([[0.299, 0.587, 0.114], [0.596, -0.274, -0.322], [0.211, -0.523, 0.312]], np.float32)
            rot = np.array([[1, 0, 0], [0, np.cos(t), -np.sin(t)], [0, np.sin(t), np.cos(t)]], np.float32)
            m = (np.linalg.inv(yiq) @ rot @ yiq).astype(np.float32)
        if sat:
            lw = np.array([0.299, 0.587, 0.114], np.float32)
            m = (np.outer(np.ones(3), lw) * -sat + np.eye(3) * (1 + sat)).astype(np.float32) @ m
        rgb8 = np.clip(rgb8.astype(np.float32) @ m.T + 0.5, 0, 255).astype(np.uint8)
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = rgb8
    out[..., 3] = a[..., 3]
    result = QtGui.QImage(out.data, w, h, w * 4, QtGui.QImage.Format.Format_RGBA8888).copy()
    result.setDevicePixelRatio(image.devicePixelRatio())
    return result.convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)


def copy_layers(layers: list) -> list:
    return copy.deepcopy(layers)


# ------------------------------------------------------------------ the panel
class LayersPanel(QtWidgets.QWidget):
    """Beside the capture: the stack (top = front). The current layer's
    blend / opacity; an adjustment layer shows its own sliders."""

    def __init__(self, overlay):
        super().__init__(overlay)
        self.o = overlay
        self.setObjectName("ltLayers")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.STYLE + "#ltLayers { background: #262626; border: 1px solid #141414; border-radius: 8px; }"
                           "#ltLayers QToolButton { border-radius: 5px; }"
                           "QLabel { color: #bdbdbd; }")
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.setFixedWidth(256)
        col = QtWidgets.QVBoxLayout(self)
        col.setContentsMargins(8, 8, 8, 8)
        col.setSpacing(6)
        # Photoshop's order: blend / opacity on top, the settings of an adjustment, the stack, the buttons
        top = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("LAYERS")
        title.setStyleSheet("color: #c9bba6; font-weight: bold; letter-spacing: 1px;")
        title.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)   # the title row moves the panel
        top.addWidget(title)
        top.addStretch(1)
        self.pin = QtWidgets.QToolButton()
        self.pin.setIcon(theme.icon("push-pin", 14))
        self.pin.setCheckable(True)
        self.pin.setFixedSize(22, 22)
        self.pin.setToolTip("Pin: the panel stays where you put it (drag it by its top)")
        self.pin.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.pin.setChecked(bool(store.get("layers_pin")))
        self.pin.toggled.connect(self._pinned)
        top.addWidget(self.pin)
        col.addLayout(top)
        self._grab_at = None
        self.blend = QtWidgets.QComboBox()
        self.blend.addItems(list(BLENDS))
        self.blend.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.blend.currentTextChanged.connect(lambda t: None if self._syncing else self._set("blend", t))
        col.addWidget(self.blend)
        self.opacity_row, self.opacity, self.opacity_num = self._slider(
            col, "Opacity", 0, 100, lambda v: self._set("opacity", v / 100))
        self.adj_title = QtWidgets.QLabel()
        self.adj_title.setStyleSheet("color: #c9bba6; font-weight: bold; letter-spacing: 1px;")
        col.addWidget(self.adj_title)
        self.adj = {}
        for key, label, low, high, _n in ADJUST:
            self.adj[key] = self._slider(col, label.replace("Levels  ", "").capitalize(), low, high,
                                         lambda v, k=key: self._set_adj(k, v))
        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #3d3d3d;")
        col.addWidget(sep)
        self.rows = QtWidgets.QVBoxLayout()
        self.rows.setSpacing(2)
        col.addLayout(self.rows)
        foot = QtWidgets.QHBoxLayout()
        foot.addStretch(1)
        for icon, tip, slot in (("plus", "New layer", lambda: self.o.add_layer()),
                                ("sliders-horizontal", "New adjustment layer (changes everything below it)",
                                 self._adjust_menu),
                                ("arrow-up", "Move layer up", lambda: self.o.move_layer(1)),
                                ("arrow-down", "Move layer down", lambda: self.o.move_layer(-1)),
                                ("stack", "Put the picked marks on this layer", self.o.marks_to_layer),
                                ("trash", "Delete layer (its marks too)", self.o.delete_layer)):
            b = QtWidgets.QToolButton()
            b.setIcon(theme.icon(icon, 15, "#c9c5bd"))
            b.setFixedSize(26, 26)
            b.setToolTip(tip)
            b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            foot.addWidget(b)
        col.addLayout(foot)
        self._thumbs = QtCore.QTimer(self)              # thumbnails follow the drawing, a little behind
        self._thumbs.setSingleShot(True)
        self._thumbs.setInterval(200)
        self._thumbs.timeout.connect(self.sync)
        self._apply = QtCore.QTimer(self)               # sliders move fast: re-filter at most every 40 ms
        self._apply.setSingleShot(True)
        self._apply.setInterval(40)
        self._apply.timeout.connect(self._refilter)
        self.sync()

    def _pinned(self, on: bool) -> None:
        store.data()["layers_pin"] = on
        if on:
            store.data()["layers_pos"] = [self.x(), self.y()]
        store.save()
        if not on:
            self.o._place_layers()

    def mousePressEvent(self, e):                                # noqa: N802
        if e.position().y() < 30 and e.button() == QtCore.Qt.MouseButton.LeftButton:
            self._grab_at = e.position().toPoint()        # drag it anywhere by its top
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):                                 # noqa: N802
        if self._grab_at is not None:
            par = self.parentWidget().rect()
            at = self.mapToParent(e.position().toPoint()) - self._grab_at
            self.move(max(0, min(par.width() - self.width(), at.x())),
                      max(0, min(par.height() - self.height(), at.y())))
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):                              # noqa: N802
        if self._grab_at is not None:
            self._grab_at = None
            self.pin.setChecked(True)                     # put somewhere by hand = it stays there
            store.data()["layers_pos"] = [self.x(), self.y()]
            store.save()
        super().mouseReleaseEvent(e)

    def _adjust_menu(self) -> None:
        menu = QtWidgets.QMenu(self)
        for kind, (name, _keys) in KINDS.items():
            menu.addAction(name, lambda k=kind: self.o.add_layer(kind=k))
        menu.exec(QtGui.QCursor.pos())

    def _slider(self, col, label, low, high, on_change):
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        name = QtWidgets.QLabel(label)
        name.setFixedWidth(76)
        s = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        s.setRange(low, high)
        s.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        num = QtWidgets.QLabel()
        num.setFixedWidth(30)
        num.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        s.valueChanged.connect(lambda v, n=num: n.setText(str(v)))
        s.valueChanged.connect(lambda v: None if self._syncing else on_change(v))
        h.addWidget(name)
        h.addWidget(s, 1)
        h.addWidget(num)
        col.addWidget(row)
        return row, s, num

    _syncing = False

    def current(self) -> dict:
        return self.o.layer(self.o.layer_id)

    def _set(self, key, value) -> None:
        layer = self.current()
        if layer is None or layer.get(key) == value:
            return
        layer[key] = value
        self.o.touch()
        self.o.update()

    def _set_adj(self, key, value) -> None:
        layer = self.current()
        if layer is None:
            return
        layer["adj"][key] = value
        self._apply.start()

    def _refilter(self) -> None:
        self.o.touch()
        self.o.update()

    def sync(self) -> None:
        """Rebuild the rows and show what the current layer has."""
        if any(not e.isReadOnly() for e in self.findChildren(QtWidgets.QLineEdit)):
            return                                        # a name being typed: not now
        self._syncing = True
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w is not None:
                w.hide()                                  # gone NOW - deleteLater alone left it drawn under the new rows
                w.setParent(None)
                w.deleteLater()
        for layer in reversed(self.o.layers):
            row = self._row(layer)
            self.rows.addWidget(row)
            row.show()                                    # shown now, so the size below counts it
        layer = self.current() or {}
        bg = layer.get("id") == BG
        kind = layer.get("kind", "")
        self.blend.setVisible(not bg and not kind)
        self.opacity_row.setVisible(not bg)
        self.adj_title.setVisible(kind in KINDS)
        shown = KINDS[kind][1] if kind in KINDS else ()
        self.adj_title.setText(KINDS[kind][0].upper() if kind in KINDS else "")
        for key, (row, s, num) in self.adj.items():
            row.setVisible(key in shown)
            s.setValue(int(layer.get("adj", NEUTRAL).get(key, NEUTRAL[key])))
            num.setText(str(s.value()))
        self.blend.setCurrentText(layer.get("blend", "Normal"))
        self.opacity.setValue(round(layer.get("opacity", 1.0) * 100))
        self.opacity_num.setText(str(self.opacity.value()))
        self._syncing = False
        self.layout().activate()
        self.setFixedHeight(self.sizeHint().height())

    def _thumb(self, layer) -> QtGui.QPixmap:
        """What is on the layer, small, over a checkerboard (Photoshop's)."""
        w, h = 44, 30
        pm = QtGui.QPixmap(w, h)
        p = QtGui.QPainter(pm)
        for y in range(0, h, 5):
            for x in range(0, w, 5):
                p.fillRect(x, y, 5, 5, QtGui.QColor("#5a5a5a" if (x // 5 + y // 5) % 2 else "#454545"))
        if layer.get("kind"):
            p.fillRect(0, 0, w, h, QtGui.QColor("#2e2a36"))
            icon = theme.icon("sliders-horizontal", 18, "#a897c4").pixmap(18, 18)
            p.drawPixmap((w - 18) // 2, (h - 18) // 2, icon)
        else:
            try:
                image = self.o._layer_image(layer, self.o.base.devicePixelRatio())
                small = image.scaled(w, h, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                     QtCore.Qt.TransformationMode.SmoothTransformation)
                small.setDevicePixelRatio(1.0)
                p.drawImage((w - small.width()) // 2, (h - small.height()) // 2, small)
            except Exception:                             # noqa: BLE001 - a thumbnail must never break the panel
                pass
        p.setPen(QtGui.QColor("#141414"))
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()
        return pm

    def _row(self, layer) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        row.setObjectName("ltLayerRow")
        row.setFixedHeight(38)
        row.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setProperty("lid", layer["id"])               # the whole row picks / drags the layer
        row.installEventFilter(self)
        active = layer["id"] == self.o.layer_id
        row.setStyleSheet("#ltLayerRow { background: %s; border-radius: 5px; border-left: 3px solid %s; }"
                          % ("#4a3420" if active else "#2c2c2c", theme.ACCENT if active else "#2c2c2c"))
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(4, 3, 6, 3)
        h.setSpacing(6)
        on = layer.get("visible", True)
        eye = QtWidgets.QToolButton()
        eye.setIcon(theme.icon("eye" if on else "eye-slash", 15, "#d4a46e" if on else "#6a6a6a"))
        eye.setFixedSize(24, 24)
        eye.setToolTip("Show / hide")
        eye.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        eye.clicked.connect(lambda _c=False, lid=layer["id"]: self.o.toggle_layer(lid))
        h.addWidget(eye)
        thumb = QtWidgets.QLabel()
        thumb.setPixmap(self._thumb(layer))
        thumb.setFixedSize(44, 30)
        thumb.setProperty("lid", layer["id"])
        thumb.installEventFilter(self)
        h.addWidget(thumb)
        name = QtWidgets.QLineEdit(layer["name"])
        name.setReadOnly(True)
        name.setFrame(False)
        name.setStyleSheet('QLineEdit { background: transparent; color: %s; %s }'
                           'QLineEdit[readOnly="false"] { background: #1c1c1c; }'
                           % ("#ffffff" if active else "#cfcfcf", "font-weight: bold;" if active else ""))
        name.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        name.installEventFilter(self)
        name.setProperty("lid", layer["id"])
        name.editingFinished.connect(lambda n=name, lid=layer["id"]: self._renamed(n, lid))
        h.addWidget(name, 1)
        if layer["id"] != BG and layer.get("opacity", 1.0) < 1:
            tag = QtWidgets.QLabel(f"{round(layer.get('opacity', 1.0) * 100)}%")
            tag.setStyleSheet("color: #8a8a8a; font-size: 10px;")
            h.addWidget(tag)
        return row

    def eventFilter(self, obj, e):                               # noqa: N802
        lid = obj.property("lid")
        E = QtCore.QEvent.Type
        editing = isinstance(obj, QtWidgets.QLineEdit) and not obj.isReadOnly()
        if lid and not editing and e.type() == E.MouseButtonPress and e.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press = (lid, e.globalPosition().toPoint(), False)
            return True
        if lid and not editing and e.type() == E.MouseMove and getattr(self, "_press", None):
            plid, start, moving = self._press
            if lid == BG and plid == BG:
                return True                               # the screenshot stays at the bottom
            if moving or (e.globalPosition().toPoint() - start).manhattanLength() >=                     QtWidgets.QApplication.startDragDistance():
                if not moving:
                    self._lift(plid)                      # the row itself comes up under the hand
                self._press = (plid, start, True)
                here = self.mapFromGlobal(e.globalPosition().toPoint())
                if self._ghost is not None:
                    self._ghost.move(self._ghost.x(), here.y() - self._ghost.height() // 2)
                    self._ghost.raise_()
                _slot, line = self._drop_slot(here)
                self._mark().setGeometry(line)
                self._mark().show()
                self._mark().raise_()
            return True
        if lid and not editing and e.type() == E.MouseButtonRelease and getattr(self, "_press", None):
            plid, _start, moving = self._press
            self._press = None
            self._mark().hide()
            self._drop_ghost()
            if moving and plid != BG:                     # dragged: it goes where the line was
                slot, _line = self._drop_slot(self.mapFromGlobal(e.globalPosition().toPoint()))
                self.o.move_layer_to(plid, slot)
            else:
                self.o.layer_id = plid                    # a click picks the layer
                QtCore.QTimer.singleShot(0, self.sync)
            return True
        if lid and e.type() == QtCore.QEvent.Type.MouseButtonDblClick and lid != BG                 and isinstance(obj, QtWidgets.QLineEdit):
            obj.setReadOnly(False)                        # double click: rename in place
            obj.setFocus()
            obj.selectAll()
            return True
        return super().eventFilter(obj, e)

    _ghost = None

    def _lift(self, lid) -> None:
        row = next((self.rows.itemAt(i).widget() for i in range(self.rows.count())
                    if self.rows.itemAt(i).widget().property("lid") == lid), None)
        if row is None:
            return
        self._ghost = QtWidgets.QLabel(self)
        self._ghost.setPixmap(row.grab())
        fade = QtWidgets.QGraphicsOpacityEffect(self._ghost)
        fade.setOpacity(0.9)
        self._ghost.setGraphicsEffect(fade)
        self._ghost.setStyleSheet(f"border: 1px solid {theme.ACCENT}; border-radius: 5px;")
        self._ghost.setGeometry(row.geometry())
        self._ghost.show()
        dim = QtWidgets.QGraphicsOpacityEffect(row)
        dim.setOpacity(0.3)
        row.setGraphicsEffect(dim)                        # its old place, faded

    def _drop_ghost(self) -> None:
        if self._ghost is not None:
            self._ghost.hide()
            self._ghost.deleteLater()
            self._ghost = None
        for i in range(self.rows.count()):
            self.rows.itemAt(i).widget().setGraphicsEffect(None)

    def _mark(self) -> QtWidgets.QFrame:
        if getattr(self, "_line", None) is None:
            self._line = QtWidgets.QFrame(self)
            self._line.setStyleSheet(f"background: {theme.ACCENT}; border: none;")
            self._line.hide()
        return self._line

    def _drop_slot(self, pos):
        """(index in the stack, bottom = 0, the line to show) for a drop at pos."""
        rows = [self.rows.itemAt(i).widget() for i in range(self.rows.count())]   # top of the stack first
        n = len(rows)
        for k, row in enumerate(rows):
            g = row.geometry()
            if pos.y() < g.center().y():
                slot = n - k                               # above this row
                return max(1, slot), QtCore.QRect(g.left(), g.top() - 2, g.width(), 3)
        g = rows[-1].geometry() if rows else QtCore.QRect()
        return 1, QtCore.QRect(g.left(), g.top() - 2, g.width(), 3)    # never under the screenshot

    def _renamed(self, edit, lid) -> None:
        layer = self.o.layer(lid)
        if layer is not None and edit.text().strip():
            layer["name"] = edit.text().strip()
        edit.setReadOnly(True)
        self.o.setFocus()

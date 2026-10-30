"""The capture: the frozen desktop over every monitor, select an area (or
click a window) and draw on it right there - no editor window (Lightshot's
way). Tools sit in a panel beside the selection; everything is a hotkey too
(letters for tools, Q for the tool ring at the cursor,
Space + drag for size / opacity, X swaps colours)."""
import datetime
import json
import math
import os
import time

from PySide6 import QtCore, QtGui, QtWidgets

from . import layers as lay
from . import shapes, store, theme
from .keys import latin
from .shapes import Shape

TOOLS = [  # kind, icon, name - the keys live in Settings (store "keys")
    ("select", "cursor", "Select / move"),
    ("brush", "paint-brush", "Brush"),
    ("eraser", "eraser", "Eraser (the brush, inverted)"),
    ("line", "line-segment", "Line"),
    ("arrow", "arrow-up-right", "Arrow"),
    ("rect", "square", "Rectangle"),
    ("ellipse", "circle", "Ellipse"),
    ("text", "text-t", "Text"),
    ("callout", "chat-circle-text", "Comment"),
    ("counter", "number-circle-one", "Number"),
    ("stamp", "sticker", "Stamp"),
    ("blur", "drop", "Blur"),
    ("pixelate", "checkerboard", "Pixelate"),
    ("spotlight", "flashlight", "Spotlight"),
    ("magnify", "magnifying-glass-plus", "Magnify"),
    ("lasso", "selection", "Selection: rectangle / lasso - hold for the choice, Shift+O switches"),
]
#: the panel's groups, each its own colour - what a tool does reads before its shape
GROUPS = (("move", "#c9c5bd", ("select", "lasso")),
          ("paint", "#d4a46e", ("brush", "eraser")),
          ("shapes", "#86a8c8", ("line", "arrow", "rect", "ellipse")),
          ("notes", "#93b88d", ("text", "callout", "counter", "stamp")),
          ("effects", "#a897c4", ("blur", "pixelate", "spotlight", "magnify")))
TOOL_COLOR = {k: c for _g, c, kinds in GROUPS for k in kinds}
_BOXES = ("rect", "ellipse", "blur", "pixelate", "spotlight", "magnify")   # tools drawn as a box
MAX_SIZE = 300.0                                          # brush size cap (60 was too small)
_MOD_KEYS = {"Alt": QtCore.Qt.Key.Key_Alt, "Ctrl": QtCore.Qt.Key.Key_Control, "Shift": QtCore.Qt.Key.Key_Shift}


def put_image(image: QtGui.QImage) -> bool:
    """The picture on the clipboard - checked, and tried again: another program holding the
    clipboard makes Windows refuse it now and then ("Ctrl+C sometimes does nothing")."""
    cb = QtWidgets.QApplication.clipboard()
    for _ in range(5):
        cb.setImage(image)
        QtWidgets.QApplication.processEvents()
        got = cb.image()
        if not got.isNull() and got.size() == image.size():
            return True
        time.sleep(0.06)
    return False


def key_of(name: str) -> str:
    return str(store.get("keys").get(name, "")).strip()


def key_name(e) -> str:
    """'W', 'Space', 'Tab', 'Shift+X'... - what Settings stores for a key."""
    mods = e.modifiers() & (QtCore.Qt.KeyboardModifier.ShiftModifier | QtCore.Qt.KeyboardModifier.AltModifier)
    key = latin(e)
    if not isinstance(key, QtCore.Qt.Key):
        return ""
    return QtGui.QKeySequence(QtCore.QKeyCombination(mods, key)).toString()


_MODS = {"Alt": QtCore.Qt.KeyboardModifier.AltModifier, "Ctrl": QtCore.Qt.KeyboardModifier.ControlModifier,
         "Shift": QtCore.Qt.KeyboardModifier.ShiftModifier}
_BUTTONS = {"middle": QtCore.Qt.MouseButton.MiddleButton, "right": QtCore.Qt.MouseButton.RightButton}


def mod_held(e, name: str) -> bool:
    flag = _MODS.get(str(store.get("mouse").get(name, "")))
    return bool(flag is not None and e.modifiers() & flag)


FONTS = ("Segoe UI", "Arial", "Calibri", "Consolas", "Georgia", "Impact", "Comic Sans MS")
HANDLE = 5
DIM = QtGui.QColor(0, 0, 0, 115)


class Overlay(QtWidgets.QWidget):
    # what W has picked: a list; `selected` is the one mark when exactly one is picked
    @property
    def selected(self):
        p = getattr(self, "picked", [])
        return p[0] if len(p) == 1 else None

    @selected.setter
    def selected(self, shape):
        self.picked = [shape] if shape is not None else []

    closed = QtCore.Signal()

    def __init__(self, app, base: QtGui.QPixmap, geo: QtCore.QRect, windows=(), preset=None, entry=None, group=None,
                 pick=None, report=None):
        super().__init__(None, QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.WindowStaysOnTopHint
                         | (QtCore.Qt.WindowType.Window if report is not None else QtCore.Qt.WindowType.Tool))
        if report is not None:                          # see-through BEFORE the window exists - later is ignored (black)
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)
            self.setWindowTitle("Report - Lead Tool")
        self.app = app
        self.group = group if group is not None else []       # the other monitors' overlays
        self.base = base
        self.geo = geo
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        while QtWidgets.QApplication.overrideCursor() is not None:     # a pipette left from before: gone
            QtWidgets.QApplication.restoreOverrideCursor()
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.setGeometry(geo)
        dpr = base.devicePixelRatio()
        self.windows = [QtCore.QRectF(r.x() / dpr - geo.x(), r.y() / dpr - geo.y(), r.width() / dpr, r.height() / dpr)
                        for r in windows]
        self.state = "select"
        self.region = QtCore.QRectF()
        self.shapes = []
        self.undo_stack, self.redo_stack = [], []
        self.tool = "brush"
        self.brush = store.get("brush") or "pen"
        self.last_end = None              # where the last stroke ended (Shift+click joins from here)
        self.picking = False              # the eyedropper key is held
        self._version = 0                 # bumped on every change of the marks (the layer cache)
        self.last_shape = None            # the mark just drawn: the wheel still sizes it
        self.flow = float(store.get("flow") or 1.0)
        self.stamp = store.get("stamp") or "check-circle"
        self.angle = float(store.get("angle") or 0.0)
        self.before_eraser = "brush"     # X toggles back to this
        self.color = QtGui.QColor(store.get("color"))
        self.color2 = QtGui.QColor(store.get("color2"))
        self.stroke = float(store.get("width"))
        self.opacity = 1.0                 # no opacity knob - a stroke covers fully; flow builds it
        self.font_name = store.get("font")
        self.text_box = bool(store.get("text_box"))
        self.text_outline = store.get("text_outline") if store.get("text_outline") is not None else "#000000"
        self.current = None           # shape being drawn
        self.selected = None
        self.drag = None              # what the mouse is doing: (kind, data)
        self.mouse = QtCore.QPointF()
        self.hover_window = None
        self.space = False
        self.hud = None               # (center, until) for size/opacity feedback
        self.text_edit = None
        self.ring = None
        self.picker = None
        self.entry_id = entry.get("id") if entry else None
        self._small_image = base.toImage()       # the loupe reads pixels from this
        self.pick = pick                        # a report asked for a screenshot: the area goes there
        self.report = report                    # this overlay IS a report (report.py)
        self.layers = lay.default_layers()      # bottom (the screenshot) first
        self.layer_id = "l1"                    # where new marks go
        self.layers_panel = None
        self.warping = None                     # the image being bent with its mesh (U)
        self.vz, self.vo = 1.0, QtCore.QPointF()   # a report's view zoom / pan (only how it is SHOWN)
        self.sel_poly = None                    # the selection (screen units)
        self.sel_mode = store.get("sel_mode") or "rect"   # Photoshop's pair: rectangle / lasso
        self.sel_bar = None
        self.panel = Panel(self)
        self.panel.hide()
        last = store.get("last_area")
        if pick is not None and preset is None and last and \
                QtCore.QRect(*[int(v) for v in last]).intersects(geo):      # the last area is on this screen
            same = QtWidgets.QPushButton(theme.icon("clock-counter-clockwise", 16, "#1a1a1a"), "  Same area  (R)", self)
            same.setStyleSheet(f"QPushButton {{ background: {theme.ACCENT}; color: #1a1a1a; font-weight: bold;"
                               f" padding: 8px 18px; border-radius: 8px; }}")
            same.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            same.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            same.adjustSize()
            same.move((geo.width() - same.width()) // 2, 18)
            same.clicked.connect(self._same_area)
        if preset is not None:
            self.region = QtCore.QRectF(preset)
            self._enter_edit()
        if entry is not None:
            self.shapes = [Shape.from_dict(d) for d in entry.get("shapes", [])]
            if entry.get("layers"):
                self.layers = entry["layers"]
                self.layer_id = next((x["id"] for x in reversed(self.layers) if x["id"] != lay.BG), lay.BG)
            for s in self.shapes:
                s.move(self.region.x(), self.region.y())
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # ------------------------------------------------------------ state
    def _visible_rect(self) -> QtCore.QRectF:
        """Where the frame (and its handles) can be: on the screen, a little inside its edges."""
        r = QtCore.QRectF(self.rect())
        if self.report is not None:                     # the report window may sit across monitors
            here = QtGui.QGuiApplication.screenAt(self.mapToGlobal(self.region.center().toPoint())) or self.screen()
            if here is not None:
                mon = here.availableGeometry()
                m = QtCore.QRectF(QtCore.QPointF(self.mapFromGlobal(mon.topLeft())), QtCore.QSizeF(mon.size()))
                if m.intersects(r):
                    r = r.intersected(m)
            bar = getattr(self, "report_bar", None)     # room over the top edge for the Task bar: it follows it up
            top = (bar.height() + 44) if bar is not None else 30
            r = r.adjusted(10, top, -10, -10)
            if self.vz != 1.0 or not self.vo.isNull():  # zoomed: the screen in report units
                r = self._view().inverted()[0].mapRect(r)
            return r
        return r.adjusted(0, 0, -1, -1)

    def _min_region(self):
        if self.report is not None:                     # the band plus some picture, always grabbable
            return 240.0, self._band() + 60.0
        return 12.0, 12.0

    def _same_area(self) -> None:
        last = store.get("last_area")
        if last and self.state == "select":
            self.region = QtCore.QRectF(last[0] - self.geo.x(), last[1] - self.geo.y(), last[2], last[3])
            self._enter_edit()
            self.update()

    def _enter_edit(self) -> None:
        self.state = "edit"
        self.region = self.region.normalized().intersected(QtCore.QRectF(self.rect()))
        if self.report is None:
            store.put("last_area", [self.region.x() + self.geo.x(), self.region.y() + self.geo.y(),
                                    self.region.width(), self.region.height()])
        if self.pick is not None:                       # for a report: hand the area over, done
            image, pick = self._base_crop(), self.pick
            self.pick = None
            QtCore.QTimer.singleShot(0, lambda: (self.close_all(), pick(image)))
            return
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.panel.show()
        self._place_panel()
        self.panel.sync()

    def _place_panel(self) -> None:
        p = self.panel
        p.adjustSize()
        r = self._vrect(self.region)
        x = r.right() + 8
        if self.report is not None:                     # a report: always on its right, never jumping sides
            x = min(x, self.width() - p.width() - 4)
        else:
            if x + p.width() > self.width() - 4:
                x = r.left() - p.width() - 8
            if x < 4:
                x = r.right() - p.width() - 6
        y = max(4, min(r.top(), self.height() - p.height() - 4))
        p.move(int(x), int(y))
        if self.__dict__.get("layers_panel") is not None and self.layers_panel.isVisible():
            self._place_layers()                            # unpinned layers follow the area

    def snapshot(self) -> tuple:
        extra = (QtCore.QRectF(self.region), dict(self.report)) if self.report is not None else None
        return [s.clone() for s in self.shapes], lay.copy_layers(self.layers), self.layer_id, extra

    def push_undo(self) -> None:
        self.touch()
        self.undo_stack.append(self.snapshot())
        del self.undo_stack[:-100]
        self.redo_stack.clear()

    def undo(self, redo=False) -> None:
        self.touch()
        src, dst = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not src:
            return
        dst.append(self.snapshot())
        shapes_, layers_, lid, extra = src.pop()
        if extra is not None and self.report is not None:
            self.region = QtCore.QRectF(extra[0])
            self.report.update(h=extra[1].get("h"), top=extra[1].get("top"), bg=extra[1].get("bg"), k=extra[1].get("k"))
            self._refill_base()
            self._report_place()
        self.shapes = [s.clone() for s in shapes_]           # instant: the strokes keep their pictures
        self.layers, self.layer_id = lay.copy_layers(layers_), lid
        self.warping = None
        if self.layers_panel is not None:
            self.layers_panel.sync()
        self.selected = None
        self.update()

    def set_brush(self, brush: str) -> None:
        from . import brushes
        self.brush = brush
        self.flow = brushes.spec(brush)["flow"]          # the preset's flow, as Painter sets it
        store.data().update(brush=brush, flow=self.flow)
        self.set_tool("brush")

    def set_tool(self, kind: str) -> None:
        self.last_shape = None
        self._finish_text()
        self.tool = kind
        if kind != "select":
            self.selected = None
        self.panel.sync()
        self.update()

    def set_color(self, color: QtGui.QColor) -> None:
        self.touch()
        self.color = QtGui.QColor(color)
        pinned = getattr(self, "pinned_picker", None)
        if pinned is not None and pinned.hex.text().upper() != self.color.name().upper():
            pinned.set_color(self.color)                    # the eyedropper / swatches update the pinned palette
        store.data()["color"] = self.color.name()
        if self.selected is not None and self.selected.kind not in ("blur", "image"):
            self.push_undo()
            self.selected.color = QtGui.QColor(color)
        if self.text_edit is not None:
            self.text_edit.shape.color = QtGui.QColor(color)
            self._style_text_edit()
        self.panel.sync()
        self.update()

    def swap_colors(self) -> None:
        self.color, self.color2 = self.color2, self.color
        store.data()["color2"] = self.color2.name()
        self.set_color(self.color)

    def set_width(self, width: float) -> None:
        self.touch()
        self.stroke = max(1.0, min(MAX_SIZE, width))
        store.data()["width"] = self.stroke
        targets = list(self.picked) or ([self.last_shape] if self.last_shape is not None else [])
        if self.current is not None:                    # the shape being drawn right now
            targets.append(self.current)
        for target in targets:
            if (target in self.shapes or target is self.current) and target.kind != "image":
                target.width = self.stroke
                target.restyle()
        if self.text_edit is not None:
            self.text_edit.shape.width = self.stroke
            self._style_text_edit()
        self.panel.sync()
        self.update()

    # ------------------------------------------------------------ painting
    def paintEvent(self, _e):                                    # noqa: N802
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self.base)
        full = QtGui.QPainterPath()
        full.addRect(QtCore.QRectF(self.rect()))
        if self.state == "select":
            live = self._drag_rect()
            hole = live if live is not None else self.hover_window
            if hole is not None:
                cut = QtGui.QPainterPath()
                cut.addRect(hole)
                full = full.subtracted(cut)
            p.fillPath(full, DIM)
            if hole is not None:
                self._paint_frame(p, hole, dashed=live is None)
            self._paint_magnifier(p)
            if live is None and hole is None:
                self._paint_hint(p, "Drag an area · click a window · R = last area · Esc")
            p.end()
            return
        cut = QtGui.QPainterPath()
        cut.addRect(self.region)
        if self.report is None:
            p.fillPath(full.subtracted(cut), DIM)
        vdpr = self.devicePixelRatioF()
        if self.report is not None and (self.vz != 1.0 or not self.vo.isNull()):
            p.setTransform(self._view())                # zoomed: drawn at the zoom's resolution, sharp
            limit = math.sqrt(48e6 / max(1.0, self.region.width() * self.region.height()))
            vdpr = max(vdpr, min(vdpr * self.vz, limit))
        self._draw_stack(p, vdpr)
        if self.text_edit is not None:
            self._paint_caret(p)
        self._paint_frame(p, self.region)
        if self.warping is not None and self.warping in self.shapes:
            self._paint_warp(p)
        elif self.picked and self.current is None:
            q = self._frame_now()
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1, QtCore.Qt.PenStyle.DashLine))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawPolygon(q)
            p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1))
            knob = self._xf_handles()["rot"].center()
            p.drawLine((q[0] + q[1]) / 2, knob)
            p.setBrush(QtGui.QColor("#ffffff"))
            for k, h in self._xf_handles().items():
                if k == "rot":
                    p.drawEllipse(h)
                else:
                    p.drawRect(h)
        sel = self.sel_poly
        if self.drag and self.drag[0] == "lasso":
            sel = QtGui.QPolygonF(self.drag[1][0])
        if sel is not None:
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            p.setBrush(QtGui.QColor(255, 255, 255, 22))
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1))
            p.drawPolygon(sel)
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1, QtCore.Qt.PenStyle.DashLine))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawPolygon(sel)
        if self.drag and self.drag[0] == "marquee":
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1, QtCore.Qt.PenStyle.DashLine))
            p.setBrush(QtGui.QColor(255, 255, 255, 18))
            p.drawRect(QtCore.QRectF(self.drag[1], self.mouse).normalized())
        if self.hud is not None:
            self._paint_hud(p)
        if self.picking:
            self._paint_pick(p)
        if self.tool in ("brush", "eraser") and self.region.contains(self.mouse) and not self.picking \
                and (not self.drag or self.drag[0] in ("flow", "adjust")):
            self._paint_tip(p)
        elif self.tool in ("blur", "pixelate") and self.region.contains(self.mouse) and not self.drag:
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 160), 1))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            r = self.stroke
            p.drawEllipse(self.mouse, max(2, r), max(2, r))
        p.end()

    def _paint_frame(self, p, r: QtCore.QRectF, dashed=False) -> None:
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1.5,
                            QtCore.Qt.PenStyle.DashLine if dashed else QtCore.Qt.PenStyle.SolidLine))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        if not dashed and self.state == "edit":
            p.setBrush(QtGui.QColor("#ffffff"))
            p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1))
            for h in self._handles().values():
                p.drawRect(h)
            grip = self._grip()                                  # the tab to move the whole area
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            p.setBrush(QtGui.QColor(theme.ACCENT))
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.drawRoundedRect(grip, 9, 9)
            p.drawImage(QtCore.QRectF(grip.center().x() - 7, grip.center().y() - 7, 14, 14),
                        theme.icon_image("arrows-out-cardinal", 28, "#1a1a1a"))
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        dpr = self.base.devicePixelRatio()
        if self.report is not None:                     # a report: the size of the PNG it saves (the pictures' pixels)
            dpr = self._report_scale()
        label = f"{round(r.width() * dpr)} × {round(r.height() * dpr)}" + ("  PNG" if self.report is not None else "")
        font = QtGui.QFont("Segoe UI")
        font.setPixelSize(12)
        p.setFont(font)
        w = QtGui.QFontMetrics(font).horizontalAdvance(label) + 12
        y = r.top() - 22 if r.top() > 26 else r.top() + 4
        box = QtCore.QRectF(r.left(), y, w, 18)
        p.fillRect(box, QtGui.QColor(20, 20, 20, 210))
        p.setPen(QtGui.QColor("#e8e8e8"))
        p.drawText(box, QtCore.Qt.AlignmentFlag.AlignCenter, label)

    def _paint_hint(self, p, text: str) -> None:
        font = QtGui.QFont("Segoe UI")
        font.setPixelSize(13)
        p.setFont(font)
        screen = QtGui.QGuiApplication.screenAt(self.mapToGlobal(self.mouse.toPoint())) \
            or QtGui.QGuiApplication.primaryScreen()
        g = screen.geometry().translated(-self.geo.topLeft())
        w = QtGui.QFontMetrics(font).horizontalAdvance(text) + 24
        box = QtCore.QRectF(g.center().x() - w / 2, g.top() + 24, w, 30)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(20, 20, 20, 220))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QtGui.QColor("#e8e8e8"))
        p.drawText(box, QtCore.Qt.AlignmentFlag.AlignCenter, text)

    def _paint_magnifier(self, p) -> None:
        """Pixel-exact loupe + the colour under the cursor (Snipaste's)."""
        dpr = self.base.devicePixelRatio()
        cx, cy = int(self.mouse.x() * dpr), int(self.mouse.y() * dpr)
        # inside the picture: a source rect past its edge crashed the raster engine
        src = QtCore.QRect(min(max(cx - 7, 0), self.base.width() - 15),
                           min(max(cy - 7, 0), self.base.height() - 15), 15, 15)
        size = 120
        x = self.mouse.x() + 22
        y = self.mouse.y() + 22
        if x + size > self.width():
            x = self.mouse.x() - size - 22
        if y + size + 26 > self.height():
            y = self.mouse.y() - size - 48
        target = QtCore.QRectF(x, y, size, size)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
        p.fillRect(target, QtGui.QColor("#000"))
        p.drawPixmap(target, self.base, QtCore.QRectF(src))
        p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1))
        p.drawRect(target)
        cell = size / 15
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 200), 1))
        p.drawRect(QtCore.QRectF(x + 7 * cell, y + 7 * cell, cell, cell))
        color = self._pixel(cx, cy)
        box = QtCore.QRectF(x, y + size + 2, size, 22)
        p.fillRect(box, QtGui.QColor(20, 20, 20, 225))
        p.fillRect(QtCore.QRectF(x + 4, y + size + 6, 14, 14), color)
        p.setPen(QtGui.QColor("#e8e8e8"))
        font = QtGui.QFont("Consolas")
        font.setPixelSize(12)
        p.setFont(font)
        p.drawText(box.adjusted(22, 0, 0, 0), QtCore.Qt.AlignmentFlag.AlignVCenter,
                   f"{color.name().upper()}  {cx},{cy}")

    def _pixel(self, x, y) -> QtGui.QColor:
        """The colour you SEE there: the screenshot with the marks over it
        (the eyedropper used to read only the screenshot under the strokes)."""
        img = self._small_image
        c = img.pixelColor(min(max(x, 0), img.width() - 1), min(max(y, 0), img.height() - 1))
        dpr = self.base.devicePixelRatio()
        if self.state != "edit" or not self.region.contains(QtCore.QPointF(x / dpr, y / dpr)):
            return c
        key = (self._version, self.region.getRect(), self._stack_sig(self.layers))   # what you see, filtered
        if getattr(self, "_seen_key", None) != key:
            self._seen, self._seen_key = self.compose(), key
        lx, ly = int(x - self.region.left() * dpr), int(y - self.region.top() * dpr)
        if not (0 <= lx < self._seen.width() and 0 <= ly < self._seen.height()):
            return c
        return self._seen.pixelColor(lx, ly)

    def _paint_tip(self, p) -> None:
        from . import brushes
        side = brushes.stamp_size(self.stroke)
        tip = brushes.tip(self.brush, side)
        c = self.hud if self.hud is not None else self.mouse
        p.save()
        p.translate(c)
        p.rotate(self.angle)
        p.setOpacity(0.25 + 0.55 * self.flow if self.hud is not None else 0.38)
        p.drawImage(QtCore.QPointF(-tip.width() / 2, -tip.height() / 2), tip)
        p.restore()
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 90), 1))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, side / 2, side / 2)

    def _paint_pick(self, p) -> None:
        """While the eyedropper key is held: a ring by the cursor - the colour
        under it (top) against the current one (bottom)."""
        dpr = self.base.devicePixelRatio()
        under = self._pixel(int(self.mouse.x() * dpr), int(self.mouse.y() * dpr))
        c = self.mouse + QtCore.QPointF(34, -34)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(20, 20, 20, 220))
        p.drawEllipse(c, 27, 27)
        p.setBrush(under)
        p.drawPie(QtCore.QRectF(c.x() - 23, c.y() - 23, 46, 46), 0, 180 * 16)
        p.setBrush(self.color)
        p.drawPie(QtCore.QRectF(c.x() - 23, c.y() - 23, 46, 46), 180 * 16, 180 * 16)
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.5))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, 23, 23)

    def _paint_hud(self, p) -> None:
        """While Space / Ctrl drags: a readout - a label, the
        number, a track - held where the drag began, above the brush. The
        tip under it shows size, angle and flow; no coloured ball over it."""
        center = self.hud
        flow = self.drag is not None and self.drag[0] == "flow"
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        if self.tool not in ("brush", "eraser"):                 # lines, frames: just how thick
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 170), 1))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawEllipse(center, max(2.0, self.stroke / 2), max(2.0, self.stroke / 2))
        if flow:
            label, shown, frac = "Flow", f"{self.flow * 100:.0f}%", math.sqrt(self.flow)
        else:
            label, shown, frac = "Size", f"{self.stroke:.0f}", math.sqrt(self.stroke / MAX_SIZE)
        from . import brushes
        half = (brushes.stamp_size(self.stroke) if self.tool in ("brush", "eraser") else self.stroke) / 2
        w, h = 150.0, 62.0
        y = center.y() - half - h - 8
        if y < self.region.top() - h and y < 0:
            y = center.y() + half + 8
        box = QtCore.QRectF(center.x() - w / 2, y, w, h)

        def text(rect, color, t):
            p.setPen(QtGui.QColor(0, 0, 0, 190))
            p.drawText(rect.translated(1, 1), QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, t)
            p.setPen(QtGui.QColor(color))
            p.drawText(rect, QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, t)

        font = QtGui.QFont("Segoe UI")
        font.setPixelSize(11)
        p.setFont(font)
        text(QtCore.QRectF(box.x() + 12, box.y() + 4, w - 24, 16), "#c9bba6", label.upper())
        font.setPixelSize(19)
        font.setBold(True)
        p.setFont(font)
        text(QtCore.QRectF(box.x() + 12, box.y() + 20, w - 24, 24), "#ffffff", shown)
        track = QtCore.QRectF(box.x() + 12, box.bottom() - 12, w - 24, 4)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 170))
        p.drawRoundedRect(track.translated(1, 1), 2, 2)
        p.setBrush(QtGui.QColor(70, 70, 70, 210))
        p.drawRoundedRect(track, 2, 2)
        filled = QtCore.QRectF(track)
        filled.setWidth(track.width() * max(0.0, min(1.0, frac)))
        p.setBrush(QtGui.QColor("#d4a46e"))
        p.drawRoundedRect(filled, 2, 2)

    # ------------------------------------------------------------ geometry helpers
    def _drag_rect(self):
        if self.drag and self.drag[0] == "new":
            start = self.drag[1]
            r = QtCore.QRectF(start, self.mouse).normalized()
            return r if r.width() > 3 and r.height() > 3 else None
        return None

    def _handles(self) -> dict:
        r = self.region
        pts = {"tl": r.topLeft(), "t": QtCore.QPointF(r.center().x(), r.top()), "tr": r.topRight(),
               "r": QtCore.QPointF(r.right(), r.center().y()), "br": r.bottomRight(),
               "b": QtCore.QPointF(r.center().x(), r.bottom()), "bl": r.bottomLeft(),
               "l": QtCore.QPointF(r.left(), r.center().y())}
        return {k: QtCore.QRectF(v.x() - HANDLE, v.y() - HANDLE, 2 * HANDLE, 2 * HANDLE) for k, v in pts.items()}

    def _grip(self) -> QtCore.QRectF:
        r = self.region
        y = r.top() - 22 if r.top() > 26 else r.top() + 4
        return QtCore.QRectF(r.center().x() - 26, y, 52, 18)

    def _handle_at(self, pos):
        if self.state == "edit" and self._grip().adjusted(-4, -4, 4, 4).contains(pos):
            return "grip"
        for k, h in self._handles().items():
            if h.adjusted(-3, -3, 3, 3).contains(pos):
                return k
        return None

    def _pick_box(self) -> QtCore.QRectF:
        b = QtCore.QRectF()
        for s in self.picked:
            b = b.united(s.bounds())
        return b.adjusted(-4, -4, 4, 4)

    def _frame_now(self) -> QtGui.QPolygonF:
        """The W frame: 4 corners (tl, tr, br, bl). Fitted when the pick
        changes, then carried along by every move / turn / stretch / distort."""
        ids = tuple(id(x) for x in self.picked)
        f = getattr(self, "_frame", None)
        if f is None or f[0] != ids:
            r = self._pick_box()
            f = self._frame = (ids, QtGui.QPolygonF([r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]))
        return QtGui.QPolygonF(f[1])

    def _set_frame(self, quad) -> None:
        self._frame = (tuple(id(x) for x in self.picked), QtGui.QPolygonF(quad))

    def _xf_handles(self) -> dict:
        q = self._frame_now()
        tl, tr, br, bl = q[0], q[1], q[2], q[3]
        top = (tl + tr) / 2
        up = top - (bl + br) / 2                          # the frame's own "up"
        n = math.hypot(up.x(), up.y()) or 1.0
        pts = {"tl": tl, "tr": tr, "br": br, "bl": bl, "t": top, "b": (bl + br) / 2,
               "l": (tl + bl) / 2, "r": (tr + br) / 2, "rot": top + up * (26 / n)}
        out = {}
        for k, pt in pts.items():
            r = 5.5 if k == "rot" else 4.5 if len(k) == 2 else 3.5
            out[k] = QtCore.QRectF(pt.x() - r, pt.y() - r, 2 * r, 2 * r)
        return out

    @staticmethod
    def _about(c, m: QtGui.QTransform) -> QtGui.QTransform:
        return QtGui.QTransform.fromTranslate(-c.x(), -c.y()) * m * QtGui.QTransform.fromTranslate(c.x(), c.y())

    def _axes(self, q):
        """Frame-aligned stretch: (angle of its x axis, unit x, unit y)."""
        u, v = q[1] - q[0], q[3] - q[0]
        a = math.degrees(math.atan2(u.y(), u.x()))
        nu, nv = math.hypot(u.x(), u.y()) or 1.0, math.hypot(v.x(), v.y()) or 1.0
        return a, u / nu, v / nv

    def _stretch(self, q, anchor, sx, sy) -> QtGui.QTransform:
        a, _u, _v = self._axes(q)
        m = QtGui.QTransform().rotate(-a) * QtGui.QTransform.fromScale(sx, sy) * QtGui.QTransform().rotate(a)
        return self._about(anchor, m)

    def flip(self, vertical=False) -> None:
        """H: mirror what is picked left-right, Shift+H: up-down (along its frame)."""
        if not self.picked:
            return
        self.push_undo()
        q = self._frame_now()
        c = sum((q[i] for i in range(4)), QtCore.QPointF()) / 4
        t = self._stretch(q, c, 1, -1) if vertical else self._stretch(q, c, -1, 1)
        for s in self.picked:
            s.xform = s.xform * t
        self._set_frame(QtGui.QPolygonF([q[1], q[0], q[3], q[2]] if not vertical else [q[3], q[2], q[1], q[0]]))
        self.touch()
        self.update()

    def _xf_at(self, pos):
        if not self.picked or self.warping is not None:
            return None
        return next((k for k, h in self._xf_handles().items() if h.adjusted(-4, -4, 4, 4).contains(pos)), None)

    def _shape_at(self, pos):
        for s in reversed(self.shapes):
            if self._shown(s) and s.hit(pos):
                return s
        return None

    # ------------------------------------------------------------ mouse
    def _end_stuck_drag(self, pos) -> None:
        """A drag whose button-up never arrived (released over another window, a dialog stole it):
        finished as if released here, so nothing keeps following the mouse."""
        kind = self.drag[0]
        if kind in ("pan", "window"):
            self.drag = None
            if kind == "window":
                self._screen_changed()
            return
        fake = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonRelease, pos, QtGui.QCursor.pos(),
                                 QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.NoButton,
                                 QtCore.Qt.KeyboardModifier.NoModifier)
        self.mouseReleaseEvent(fake)
        self.drag = None

    def focusOutEvent(self, e):                                  # noqa: N802
        if self.picking:
            self._stop_picking()
        super().focusOutEvent(e)

    def mousePressEvent(self, e):                                # noqa: N802
        if self.picking and not self._picking_held():
            self._stop_picking()
        self.touch()
        pos = e.position()
        self.mouse = pos
        if self.ring is not None:
            return
        picker = _BUTTONS.get(str(store.get("mouse").get("picker", "")))
        if self.report is not None and e.button() == QtCore.Qt.MouseButton.MiddleButton:
            self.drag = ("pan", (e.globalPosition(), QtCore.QPointF(self.vo), False))   # middle drag: pan
            return
        if self.state == "edit" and picker is not None and e.button() == picker:
            self.open_picker_at(e.globalPosition().toPoint())      # the palette under the cursor
            return
        menu_button = QtCore.Qt.MouseButton.MiddleButton if picker == QtCore.Qt.MouseButton.RightButton \
            else QtCore.Qt.MouseButton.RightButton
        if e.button() == menu_button:
            if self.current is not None:
                self.current = None
                self.drag = None
                self.update()
            elif self.state == "edit":
                self._context_menu(e.globalPosition().toPoint())
            else:
                self.close_all()
            return
        if e.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        if self.state == "select":
            self.drag = ("new", pos)
            for other in list(self.group):         # this monitor is the capture: the others come back
                if other is not self:
                    other.close()
            return
        if self.space:
            self.drag = ("adjust", (pos, self.stroke, self.opacity))
            self.hud = pos
            self.update()
            return
        self._finish_text()
        if mod_held(e, "flow") and self.tool not in ("select", "text") and not (
                mod_held(e, "move") and self._shape_at(pos) is not None):
            self.drag = ("flow", (pos, self.flow, self.angle))
            self.hud = pos
            self.update()
            return
        if mod_held(e, "eyedropper") and self.region.contains(pos):
            dpr = self.base.devicePixelRatio()
            self.set_color(self._pixel(int(pos.x() * dpr), int(pos.y() * dpr)))
            return
        if mod_held(e, "move"):
            hit = self._shape_at(pos)
            if hit is not None:                 # move what is there, whatever the tool
                self.selected = hit
                self.push_undo()
                self.drag = ("move", pos)
                self.update()
                return
        if self.warping is not None and self._warp_press(pos):
            return
        which = self._xf_at(pos)
        if which is not None:                     # turn / scale what is picked
            self.push_undo()
            self.drag = ("xf", (which, pos, self._frame_now(), [(s, QtGui.QTransform(s.xform)) for s in self.picked]))
            self._xf_mods = e.modifiers()
            return
        handle = self._handle_at(pos)
        if handle is not None:
            if self.report is not None and handle == "grip":
                self.drag = ("window", (QtGui.QCursor.pos(), self.pos()))
                return
            self.drag = ("region", ("move" if handle == "grip" else handle, pos, QtCore.QRectF(self.region)))
            return
        if self.tool == "select":
            hit = self._shape_at(pos)
            shift = bool(e.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
            if hit is not None:
                self.layer_id = self._marks_layer(hit)     # its layer becomes the current one (Auto-Select)
                if self.layers_panel is not None and self.layers_panel.isVisible():
                    self.layers_panel.sync()
                if shift:                                  # Shift: add / take away
                    self.picked = [s for s in self.picked if s is not hit] if hit in self.picked \
                        else self.picked + [hit]
                elif hit not in self.picked:
                    self.picked = [hit]
                self.push_undo()
                self.drag = ("move", pos)
            elif self.region.contains(pos):                # empty place: a frame picks what it touches
                if not shift:
                    self.picked = []
                self.drag = ("marquee", pos)
            self.update()
            return
        if not self.region.contains(pos):
            return
        if self.tool == "lasso":                       # a new selection: a rectangle or a lasso (Shift = the other one)
            self._set_selection(None)
            rect = (self.sel_mode == "rect") != bool(e.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
            self.drag = ("lasso", ([pos], rect))
            return
        if self.tool == "callout":
            hit = self._shape_at(pos)
            if hit is not None and hit.kind == "callout":
                self._edit_text(hit, pos)
                return
        if self.tool == "text":
            hit = self._shape_at(pos)
            self._edit_text(hit if hit is not None and hit.kind in ("text", "callout") else None, pos)
            return
        self.push_undo()
        s = Shape("stroke" if self.tool in ("brush", "eraser") else self.tool, self.color, self.stroke, self.opacity)
        s.layer = self._draw_layer_id()
        s.brush = self.brush
        s.flow = self.flow
        s.angle = self.angle
        s.erase = self.tool == "eraser"
        if self.tool == "stamp":
            s.points = [pos]
            s.text = self.stamp
            self.shapes.append(s)
            self._made = (s, time.monotonic())
            self.update()
            return
        if self.tool == "callout":
            s.points = [pos, pos]                     # the tip, then where the bubble goes
            s.font = self.font_name
            self.current = s
            self.drag = ("draw", pos)
            return
        if self.tool == "counter":
            s.points = [pos]
            s.number = 1 + max([x.number for x in self.shapes if x.kind == "counter"] or [0])
            self.shapes.append(s)
            self._made = (s, time.monotonic())
            self.update()
            return
        if self.tool in _BOXES:
            s.rect = QtCore.QRectF(pos, pos)
        else:
            s.points = [pos, pos] if self.tool in ("line", "arrow") else [pos]
        self.joining = bool(e.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier) \
            and self.last_end is not None and s.kind in ("stroke", "line", "arrow")
        if self.joining:
            s.points = [QtCore.QPointF(self.last_end), pos]
        self.current = s
        self.drag = ("draw", pos)

    def _stop_picking(self) -> None:
        self.picking = False
        while QtWidgets.QApplication.overrideCursor() is not None:     # every stacked one, not just the last
            QtWidgets.QApplication.restoreOverrideCursor()
        self.update()

    def _picking_held(self) -> bool:
        name = str(store.get("mouse").get("eyedropper", ""))
        mods = QtGui.QGuiApplication.queryKeyboardModifiers()
        return {"Alt": QtCore.Qt.KeyboardModifier.AltModifier, "Ctrl": QtCore.Qt.KeyboardModifier.ControlModifier,
                "Shift": QtCore.Qt.KeyboardModifier.ShiftModifier}.get(name, QtCore.Qt.KeyboardModifier.NoModifier) & mods \
            if name in ("Alt", "Ctrl", "Shift") else False

    def mouseMoveEvent(self, e):                                 # noqa: N802
        pos = e.position()
        self.mouse = pos
        if self.drag and e.buttons() == QtCore.Qt.MouseButton.NoButton and self.drag[0] in (
                "pan", "window", "move", "xf", "region", "marquee", "warp", "lasso", "draw", "adjust", "flow"):
            self._end_stuck_drag(pos)                   # the button went up where we did not hear it
        if self.picking and not self._picking_held():
            self._stop_picking()
        if self.picking:
            self.update()
        shift = bool(e.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
        if self.state == "select":
            if not self.drag:
                self.hover_window = next((w for w in self.windows if w.contains(pos)), None)
            self.update()
            return
        kind = self.drag[0] if self.drag else None
        if kind == "flow":
            start, flow0, angle0 = self.drag[1]
            f = max(0.0, min(1.0, math.sqrt(flow0) + (pos.x() - start.x()) / 400))
            self.flow = max(0.01, f * f)                 # squared, like Painter's sliders: the low end gets the travel
            self.angle = (angle0 + (pos.y() - start.y()) * 0.6) % 360
            store.data().update(flow=self.flow, angle=self.angle)
            self.panel.sync()
        elif kind == "adjust":
            start, width0, _op0 = self.drag[1]
            self.stroke = max(1.0, min(MAX_SIZE, width0 * math.exp((pos.x() - start.x()) / 160)))
            store.data().update(width=self.stroke)
            self.panel.sync()
        elif kind == "draw":
            s = self.current
            if s.kind == "callout":
                s.points[1] = pos
            elif s.kind in _BOXES:
                start = self.drag[1]
                end = pos
                if shift:                                         # square / circle
                    side = max(abs(pos.x() - start.x()), abs(pos.y() - start.y()))
                    end = QtCore.QPointF(start.x() + math.copysign(side, pos.x() - start.x()),
                                         start.y() + math.copysign(side, pos.y() - start.y()))
                s.rect = QtCore.QRectF(start, end)
            elif getattr(self, "joining", False):                # Shift+click line: the end follows the hand
                s.points = [s.points[0], pos]
                s.restyle()
            elif s.kind in ("line", "arrow"):
                s.points[-1] = shapes.constrain(s.points[0], pos) if shift else pos
            else:
                if shift:                                         # straight from where you pressed
                    s.points = [s.points[0], shapes.constrain(s.points[0], pos)]
                    s.restyle()                                   # a new line, stamped again
                else:
                    s.points.append(pos)
        elif kind == "move":
            self.touch()
            delta = pos - self.drag[1]
            for s in self.picked:
                s.move(delta.x(), delta.y())
            self._set_frame(self._frame_now().translated(delta))
            self.drag = ("move", pos)
        elif kind == "marquee":
            self.update()
        elif kind == "lasso":
            pts, rect = self.drag[1]
            if rect:
                r = QtCore.QRectF(pts[0], pos).normalized()
                self.drag = ("lasso", ([pts[0], r.topRight(), r.bottomRight(), r.bottomLeft(), r.topLeft(), pos], True))
            else:
                pts.append(pos)
            self.update()
        elif kind == "warp":
            self._warp_move(pos)
        elif kind == "xf":
            self.touch()
            which, start, q0, before = self.drag[1]
            mods = e.modifiers() | getattr(self, "_xf_mods", QtCore.Qt.KeyboardModifier.NoModifier)
            ctrl = bool(mods & QtCore.Qt.KeyboardModifier.ControlModifier)       # held at the press counts too
            corner = {"tl": 0, "tr": 1, "br": 2, "bl": 3}
            c = sum((q0[i] for i in range(4)), QtCore.QPointF()) / 4
            if which == "rot":                             # turn round the middle; Shift = 15 degree steps
                deg = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x())
                                   - math.atan2(start.y() - c.y(), start.x() - c.x()))
                if shift:
                    a0 = self._axes(q0)[0]
                    deg = round((a0 + deg) / 15) * 15 - a0
                t = self._about(c, QtGui.QTransform().rotate(deg))
            elif which in corner and ctrl:                 # Ctrl + corner: that corner alone (distort)
                q1 = QtGui.QPolygonF(q0)
                q1[corner[which]] = pos
                t = QtGui.QTransform.quadToQuad(q0, q1) or QtGui.QTransform()
            elif which in corner:                          # a corner: in proportion; Shift = free stretch
                i = corner[which]
                anchor = q0[(i + 2) % 4]
                d0, d1 = start - anchor, pos - anchor
                if shift:
                    _a, u, v = self._axes(q0)
                    dot = lambda p_, w: p_.x() * w.x() + p_.y() * w.y()
                    sx = dot(d1, u) / (dot(d0, u) or 1.0)
                    sy = dot(d1, v) / (dot(d0, v) or 1.0)
                    t = self._stretch(q0, anchor, sx, sy)
                else:
                    k = max(0.05, (d0.x() * d1.x() + d0.y() * d1.y()) / max(1.0, d0.x() ** 2 + d0.y() ** 2))
                    t = self._about(anchor, QtGui.QTransform.fromScale(k, k))
            else:                                          # a side: stretch along one axis (negative = flip)
                _a, u, v = self._axes(q0)
                mid = {"t": (q0[3] + q0[2]) / 2, "b": (q0[0] + q0[1]) / 2,
                       "l": (q0[1] + q0[2]) / 2, "r": (q0[0] + q0[3]) / 2}[which]
                w = u if which in ("l", "r") else v
                d0, d1 = start - mid, pos - mid
                k = (d1.x() * w.x() + d1.y() * w.y()) / ((d0.x() * w.x() + d0.y() * w.y()) or 1.0)
                k = k if abs(k) > 0.03 else 0.03
                t = self._stretch(q0, mid, k, 1) if which in ("l", "r") else self._stretch(q0, mid, 1, k)
            for s, x0 in before:
                s.xform = x0 * t
            self._set_frame(t.map(q0))
        elif kind == "pan":
            start, vo0, _moved = self.drag[1]
            d = e.globalPosition() - start
            if d.manhattanLength() > 4:
                self.drag = ("pan", (start, vo0, True))
                self.vo = vo0 + d
                self._report_place()
                self.update()
        elif kind == "window":
            start, at = self.drag[1]
            self.move(at + (QtGui.QCursor.pos() - start))
        elif kind == "region":
            which, start, r0 = self.drag[1]
            d = pos - start
            r = QtCore.QRectF(r0)
            vis = self._visible_rect()
            min_w, min_h = self._min_region()
            if which == "move":
                r.translate(d)
                r.moveLeft(min(max(r.left(), vis.left()), vis.right() - r.width()))
                r.moveTop(min(max(r.top(), vis.top()), vis.bottom() - r.height()))
            else:                                       # each side stops at the screen and short of the other side
                if "l" in which:
                    r.setLeft(min(max(r0.left() + d.x(), vis.left()), r0.right() - min_w))
                if "r" in which:
                    r.setRight(max(min(r0.right() + d.x(), vis.right()), r0.left() + min_w))
                if "t" in which:
                    r.setTop(min(max(r0.top() + d.y(), vis.top()), r0.bottom() - min_h))
                if "b" in which:
                    r.setBottom(max(min(r0.bottom() + d.y(), vis.bottom()), r0.top() + min_h))
            self.region = r
            self._place_panel()
            if self.report is not None:
                self._report_place()
        else:
            handle = self._handle_at(pos)
            cursors = {"tl": QtCore.Qt.CursorShape.SizeFDiagCursor, "br": QtCore.Qt.CursorShape.SizeFDiagCursor,
                       "tr": QtCore.Qt.CursorShape.SizeBDiagCursor, "bl": QtCore.Qt.CursorShape.SizeBDiagCursor,
                       "t": QtCore.Qt.CursorShape.SizeVerCursor, "b": QtCore.Qt.CursorShape.SizeVerCursor,
                       "l": QtCore.Qt.CursorShape.SizeHorCursor, "r": QtCore.Qt.CursorShape.SizeHorCursor}
            if handle == "grip":
                self.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
            elif handle:
                self.setCursor(cursors[handle])
            elif self.tool == "select":
                self.setCursor(QtCore.Qt.CursorShape.SizeAllCursor if self._shape_at(pos)
                               else QtCore.Qt.CursorShape.ArrowCursor)
            elif self.tool == "text":
                self.setCursor(QtCore.Qt.CursorShape.IBeamCursor)
            else:
                self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        self.update()

    def mouseReleaseEvent(self, e):                              # noqa: N802
        self.touch()
        if self.drag and self.drag[0] == "pan" and e.button() == QtCore.Qt.MouseButton.MiddleButton:
            moved = self.drag[1][2]
            self.drag = None
            if not moved and self.state == "edit":      # a middle click without a drag: what it did before
                picker = _BUTTONS.get(str(store.get("mouse").get("picker", "")))
                if picker != QtCore.Qt.MouseButton.MiddleButton:
                    self._context_menu(e.globalPosition().toPoint())
                else:
                    self.open_picker_at(e.globalPosition().toPoint())
            return
        if e.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        kind = self.drag[0] if self.drag else None
        if self.state == "select":
            r = self._drag_rect()
            self.drag = None
            if r is None and self.hover_window is not None:
                r = self.hover_window
            if r is not None:
                self.region = r
                self._enter_edit()
            self.update()
            return
        if kind == "draw" and self.current is not None:
            s = self.current
            if getattr(self, "joining", False):           # the line ends where the button comes up
                s.points = [s.points[0], e.position()]
                s.restyle()
            self.joining = False
            if s.kind in ("stroke", "line", "arrow") and s.points:
                self.last_end = QtCore.QPointF(s.points[-1])
            if s.kind == "callout":                       # the bubble is where you let go: type in it
                if (s.points[1] - s.points[0]).manhattanLength() < 12:    # a click: the bubble right there,
                    s.points[0] = s.points[1] + QtCore.QPointF(-18, 34)    # a short tail down-left
                self.shapes.append(s)
                self.current = None
                self.drag = None
                self.set_tool("callout")
                self._edit_text(s, s.points[1])
                return
            if s.kind == "magnify":                       # the lens beside what it shows, inside the area
                r = s.rect.normalized()
                radius = max(24.0, max(r.width(), r.height()))
                x = r.right() + radius * 1.3
                if x + radius > self.region.right():
                    x = r.left() - radius * 1.3
                y = min(max(r.center().y(), self.region.top() + radius), self.region.bottom() - radius)
                s.points = [QtCore.QPointF(x, y)]
            b = s.bounds()
            if s.kind == "stroke" and len(s.points) == 1:
                s.points.append(s.points[0])
            if s.erase and self._attach_cut(s):
                pass                                        # the eraser lives on the marks it cut
            elif b.width() > 2 or b.height() > 2 or s.kind == "stroke":
                self.shapes.append(s)
                self._made = (s, time.monotonic())
                self.last_shape = s if s.kind != "stroke" else None
            else:
                self.undo_stack.pop()
            self.current = None
        if kind == "window":
            self.drag = None
            self._screen_changed()
            return
        if kind in ("adjust", "flow"):
            self.hud = None
            store.save()
        if kind == "lasso":
            pts, rect = self.drag[1]
            if rect:
                r = QtCore.QRectF(pts[0], e.position()).normalized()
                pts = [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]
            poly = QtGui.QPolygonF(pts)
            b = poly.boundingRect()
            self._set_selection(poly if b.width() > 3 and b.height() > 3 else None)
        if kind == "marquee":
            frame = QtCore.QRectF(self.drag[1], e.position()).normalized()
            if frame.width() > 3 or frame.height() > 3:
                self.picked += [s for s in self.shapes if not s.erase and s not in self.picked
                                and self._shown(s) and frame.intersects(s.bounds())]
        self.drag = None
        self.update()

    def mouseDoubleClickEvent(self, e):                          # noqa: N802
        """Double click a text, a comment or a number: edit it - whatever
        tool is in hand. The first click of the double click may have put a
        dot / a number / a stamp down on top of it: that is taken back."""
        if self.state != "edit":
            return
        if self.report is not None:                     # double click the logo: your own logo file
            from . import report as rp
            band = self._band()
            if rp.logo_rect(self.region, band).adjusted(-8, -8, 8, 8).contains(e.position()):
                path, _f = QtWidgets.QFileDialog.getOpenFileName(
                    self, "Logo for the reports", os.path.expanduser("~"), "Pictures (*.png *.jpg *.jpeg *.webp *.bmp)")
                if path and rp.set_logo(path):
                    self.touch()
                    self.update()
                return
        made, when = getattr(self, "_made", (None, 0.0))
        fresh = made is not None and made in self.shapes and \
            time.monotonic() - when < QtWidgets.QApplication.doubleClickInterval() / 1000 + 0.15
        pos = e.position()
        hit = next((x for x in reversed(self.shapes) if (x is not made or not fresh) and x.kind in ("counter", "text", "callout")
                    and x.hit(pos)), None)
        if hit is None:
            return
        if fresh:
            self.shapes.remove(made)
            if self.undo_stack:
                self.undo_stack.pop()                   # the snapshot taken for the stray mark
            self._made = (None, 0.0)
        self.current = None
        self.drag = None
        self._finish_text()
        self._edit_text(hit, pos)

    def wheelEvent(self, e):                                     # noqa: N802
        step = 1 if e.angleDelta().y() > 0 else -1
        mods = e.modifiers()
        if self.report is not None and mods & (QtCore.Qt.KeyboardModifier.ShiftModifier
                                               | QtCore.Qt.KeyboardModifier.AltModifier):
            self.zoom_view(1.2 if (e.angleDelta().y() or e.angleDelta().x()) > 0 else 1 / 1.2, e.position())
            return
        if e.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:     # thickness, whatever is going on
            self.set_width(self.stroke * (1.12 if step > 0 else 1 / 1.12) if self.stroke > 8 else self.stroke + step)
            return
        if self.selected is not None and self.selected.kind == "image":
            r = self.selected.rect.normalized()
            k = 1.08 if step > 0 else 1 / 1.08
            c = r.center()
            self.selected.rect = QtCore.QRectF(c.x() - r.width() * k / 2, c.y() - r.height() * k / 2,
                                               r.width() * k, r.height() * k)
            self.update()
            return
        self.set_width(self.stroke * (1.12 if step > 0 else 1 / 1.12) if self.stroke > 8 else self.stroke + step)

    # ------------------------------------------------------------ keys
    def keyPressEvent(self, e):                                  # noqa: N802
        self.touch()
        if self.text_edit is not None and self._text_key(e):
            return
        if self.state == "edit" and self._picking_key(e) and not e.isAutoRepeat() and not self.picking:
            self.picking = True
            QtWidgets.QApplication.setOverrideCursor(_eyedropper_cursor())
            self.update()
            return
        key, mods = latin(e), e.modifiers()
        ctrl = bool(mods & QtCore.Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & QtCore.Qt.KeyboardModifier.ShiftModifier)
        if self.sel_poly is not None and self.text_edit is None:
            alt = bool(mods & QtCore.Qt.KeyboardModifier.AltModifier)
            if key == QtCore.Qt.Key.Key_Escape:
                self._set_selection(None)
                return
            if key == QtCore.Qt.Key.Key_Backspace and alt:      # Photoshop's Alt+Backspace: fill
                self.fill_selection()
                return
            if key in (QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace):
                self.erase_selection()
                return
        if self.warping is not None and key in (QtCore.Qt.Key.Key_Escape, QtCore.Qt.Key.Key_Return,
                                                QtCore.Qt.Key.Key_Enter, QtCore.Qt.Key.Key_U):
            self.end_warp()
            return
        if key == QtCore.Qt.Key.Key_O and shift and self.state == "edit":
            self.set_sel_mode("lasso" if self.sel_mode == "rect" else "rect")
            return
        if key == QtCore.Qt.Key.Key_R and ctrl and self.report is not None:
            self.reset_zoom()                               # Ctrl+R: the whole report again
            return
        if key == QtCore.Qt.Key.Key_F7:
            self.toggle_layers_panel()
            return
        if key == QtCore.Qt.Key.Key_U and not ctrl and self.state == "edit":
            self.start_warp()
            return
        if key == QtCore.Qt.Key.Key_Escape:
            if self.ring is not None:
                self.ring.close()
            elif self.current is not None:
                self.current = None
                self.drag = None
            elif self.picked:
                self.picked = []
            else:
                self.close_all()
            self.update()
            return
        if self.state == "select":
            if key == QtCore.Qt.Key.Key_R:
                self._same_area()
            elif key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                self.region = QtCore.QRectF(self.rect())
                self._enter_edit()
                self.update()
            return
        name = key_name(e)
        if name and name == key_of("adjust") and not e.isAutoRepeat():
            self.space = True
            self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
            return
        if ctrl:
            actions = {QtCore.Qt.Key.Key_Z: lambda: self.undo(redo=shift), QtCore.Qt.Key.Key_Y: lambda: self.undo(True),
                       QtCore.Qt.Key.Key_C: self.copy_marks if (self.picked and self.report is not None)
                       else self.copy_and_close,
                       QtCore.Qt.Key.Key_S: self.save,
                       QtCore.Qt.Key.Key_V: self.paste, QtCore.Qt.Key.Key_P: self.pin,
                       QtCore.Qt.Key.Key_T: self.ocr, QtCore.Qt.Key.Key_X: self.delete_selected}
            if key in actions:
                actions[key]()
            return
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self.copy_and_close()
            return
        if key == QtCore.Qt.Key.Key_Delete:
            self.delete_selected()
            return
        if key == QtCore.Qt.Key.Key_H and self.picked and self.state == "edit":
            self.flip(vertical=shift)
            return
        if key in (QtCore.Qt.Key.Key_BracketLeft, QtCore.Qt.Key.Key_BracketRight):
            up = key == QtCore.Qt.Key.Key_BracketRight
            self.set_width(self.stroke * (1.12 if up else 1 / 1.12) if self.stroke > 8 else self.stroke + (1 if up else -1))
            return
        if QtCore.Qt.Key.Key_1 <= key <= QtCore.Qt.Key.Key_9:
            colors = store.get("colors")
            i = key - QtCore.Qt.Key.Key_1
            if i < len(colors):
                self.set_color(QtGui.QColor(colors[i]))
            return
        if e.isAutoRepeat() or not name:
            return
        if name == key_of("brushes"):
            self.open_ring()
        elif name == key_of("pie"):
            self.open_pie()
        elif name == key_of("swap"):
            self.swap_colors()
        elif name == key_of("picker"):
            self.open_picker_at(QtGui.QCursor.pos())
        elif name == key_of("eraser"):
            # a toggle: X again goes back to what was in hand
            if self.tool == "eraser":
                self.set_tool(self.before_eraser)
            else:
                self.before_eraser = self.tool if self.tool != "eraser" else "brush"
                self.set_tool("eraser")
        else:
            for kind, _icon, _name in TOOLS:
                if name == key_of(kind):
                    self.set_tool(kind)
                    return

    def close_all(self) -> None:
        for other in list(self.group):
            if other is not self:
                other.close()
        self.close()

    def enterEvent(self, e):                                     # noqa: N802
        """Choosing a monitor: the keys follow the mouse (R, Enter, Esc)."""
        if self.state == "select" and len(self.group) > 1:
            self.activateWindow()
            self.setFocus()
        super().enterEvent(e)

    def delete_selected(self) -> None:
        gone = [s for s in self.picked if s in self.shapes]
        if gone:
            self.push_undo()
            self.shapes = [s for s in self.shapes if s not in gone]
            self.picked = []
            self.update()

    def _view(self) -> QtGui.QTransform:
        return QtGui.QTransform().translate(self.vo.x(), self.vo.y()).scale(self.vz, self.vz)

    def _vrect(self, r: QtCore.QRectF) -> QtCore.QRectF:
        """A report rect where it shows on screen (zoom / pan applied) - for placing the bars."""
        if self.report is None or (self.vz == 1.0 and self.vo.isNull()):
            return QtCore.QRectF(r)
        return self._view().mapRect(QtCore.QRectF(r))

    def reset_zoom(self) -> None:
        self.vz, self.vo = 1.0, QtCore.QPointF()
        self._report_place()
        self.update()

    def _zoom_button(self) -> None:
        """While zoomed: a button at the bottom of the screen - the zoom, and a click back to normal."""
        zoomed = self.vz != 1.0 or not self.vo.isNull()
        b = getattr(self, "zoom_btn", None)
        if not zoomed:
            if b is not None:
                b.hide()
            return
        if b is None:
            b = self.zoom_btn = QtWidgets.QPushButton(self)
            b.setStyleSheet(f"QPushButton {{ background: #262626; color: #e0e0e0; border: 1px solid {theme.ACCENT};"
                            f" border-radius: 8px; padding: 6px 14px; font-weight: bold; }}")
            b.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            b.setToolTip("Back to the whole report  (Ctrl+R)")
            b.clicked.connect(self.reset_zoom)
        b.setText(f"{round(self.vz * 100)}%   Reset zoom  (Ctrl+R)")
        b.adjustSize()
        here = QtGui.QGuiApplication.screenAt(self.mapToGlobal(self.rect().center())) or self.screen()
        mon = here.availableGeometry() if here is not None else self.geometry()
        bottom = self.mapFromGlobal(QtCore.QPoint(mon.center().x(), mon.bottom()))
        b.move(int(bottom.x() - b.width() / 2), int(bottom.y() - b.height() - 18))
        b.show()
        b.raise_()

    def zoom_view(self, factor: float, at: QtCore.QPointF) -> None:
        z = min(16.0, max(0.25, self.vz * factor))
        logical = (at - self.vo) / self.vz              # the point under the cursor stays under it
        self.vo = at - logical * z
        self.vz = z
        if abs(self.vz - 1.0) < 1e-3 and (self.vo.manhattanLength() < 2):
            self.vz, self.vo = 1.0, QtCore.QPointF()
        self._report_place()
        self.update()

    def event(self, e):                                          # noqa: A003
        if getattr(self, "report", None) is not None and (self.vz != 1.0 or not self.vo.isNull()) and e.type() in (
                QtCore.QEvent.Type.MouseButtonPress, QtCore.QEvent.Type.MouseButtonRelease,
                QtCore.QEvent.Type.MouseMove, QtCore.QEvent.Type.MouseButtonDblClick):
            # zoomed: the mouse speaks in report units, everything else stays as it was
            inv = self._view().inverted()[0]
            mapped = QtGui.QMouseEvent(e.type(), inv.map(e.position()), e.globalPosition(),
                                       e.button(), e.buttons(), e.modifiers())
            return super().event(mapped)
        # Tab would move the keyboard focus - here it opens the pie
        if e.type() == QtCore.QEvent.Type.KeyPress and e.key() in (QtCore.Qt.Key.Key_Tab, QtCore.Qt.Key.Key_Backtab):
            self.keyPressEvent(e)
            return True
        return super().event(e)

    def _picking_key(self, e) -> bool:
        return e.key() == _MOD_KEYS.get(str(store.get("mouse").get("eyedropper", "")))

    def keyReleaseEvent(self, e):                                # noqa: N802
        if self._picking_key(e) and self.picking:
            self._stop_picking()
            return
        if key_name(e) == key_of("adjust") and not e.isAutoRepeat():
            self.space = False
            self.hud = None
            self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
            self.update()

    # ------------------------------------------------------------ text
    def _edit_text(self, shape, pos) -> None:
        """Type straight onto the picture: the letters appear as the final
        text, a caret blinks in it - no edit box over it."""
        self.push_undo()
        if shape is None:
            shape = Shape("text", self.color, self.stroke, self.opacity)
            shape.layer = self._draw_layer_id()
            shape.points = [pos]
            shape.font, shape.box = self.font_name, self.text_box
            shape.outline = self.text_outline
            self.shapes.append(shape)
        self.text_edit = _TextSession(shape, len(shape.text))
        self.activateWindow()                          # the keys come here at once - no second click
        self.setFocus()
        if getattr(self, "_blink", None) is None:
            self._blink = QtCore.QTimer(self)
            self._blink.setInterval(530)
            self._blink.timeout.connect(self._toggle_caret)
        self._blink.start()
        self.setFocus()
        self.update()

    def _toggle_caret(self) -> None:
        if self.text_edit is not None:
            self.text_edit.on = not self.text_edit.on
            self.update()

    def _style_text_edit(self) -> None:
        self.update()

    def _text_key(self, e) -> bool:
        """Keys while typing: letters, Shift+Enter (new line), Backspace / Delete,
        arrows / Home / End, Ctrl+V; Enter, Esc or a click outside end it."""
        t = self.text_edit
        s = t.shape
        key, mods = latin(e), e.modifiers()
        ctrl = bool(mods & QtCore.Qt.KeyboardModifier.ControlModifier)
        K = QtCore.Qt.Key
        shift = bool(mods & QtCore.Qt.KeyboardModifier.ShiftModifier)
        if key == K.Key_Escape or (key in (K.Key_Return, K.Key_Enter) and not shift):
            self._finish_text()                       # Enter applies, Shift+Enter = a new line
        elif key in (K.Key_Return, K.Key_Enter):
            s.text = s.text[:t.caret] + "\n" + s.text[t.caret:]
            t.caret += 1
        elif key == K.Key_Backspace:
            if t.caret:
                s.text = s.text[:t.caret - 1] + s.text[t.caret:]
                t.caret -= 1
        elif key == K.Key_Delete:
            s.text = s.text[:t.caret] + s.text[t.caret + 1:]
        elif key == K.Key_Left:
            t.caret = max(0, t.caret - 1)
        elif key == K.Key_Right:
            t.caret = min(len(s.text), t.caret + 1)
        elif key == K.Key_Home:
            t.caret = s.text.rfind("\n", 0, t.caret) + 1
        elif key == K.Key_End:
            end = s.text.find("\n", t.caret)
            t.caret = len(s.text) if end < 0 else end
        elif ctrl and key == K.Key_V:
            pasted = QtWidgets.QApplication.clipboard().text()
            s.text = s.text[:t.caret] + pasted + s.text[t.caret:]
            t.caret += len(pasted)
        elif e.text() and e.text().isprintable() and not ctrl:
            s.text = s.text[:t.caret] + e.text() + s.text[t.caret:]
            t.caret += len(e.text())
        else:
            return False
        t.on = True
        self.update()
        return True

    def _paint_caret(self, p) -> None:
        t = self.text_edit
        s = t.shape
        rect = s.text_rect()
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 110), 1, QtCore.Qt.PenStyle.DashLine))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRect(rect.adjusted(-3, -3, 3, 3))
        if not t.on:
            return
        metrics = QtGui.QFontMetricsF(s.qfont())
        before = s.text[:t.caret].split("\n")
        pad = s.pad()
        x = rect.x() + pad + metrics.horizontalAdvance(before[-1])
        y = rect.y() + pad + (len(before) - 1) * metrics.lineSpacing()
        p.setPen(QtGui.QPen(s.color, max(1.5, metrics.height() / 14)))
        p.drawLine(QtCore.QPointF(x, y + 1), QtCore.QPointF(x, y + metrics.ascent() + metrics.descent() - 1))

    def _finish_text(self) -> None:
        t, self.text_edit = self.text_edit, None
        if t is None:
            return
        if getattr(self, "_blink", None):
            self._blink.stop()
        s = t.shape
        s.text = s.text.rstrip()
        if not s.text and s.kind in ("text", "callout") and s in self.shapes:
            self.shapes.remove(s)
        self.setFocus()
        self.update()

    # ------------------------------------------------------------ the tool ring (Q)
    def open_ring(self) -> None:
        """Q: the brushes as a scroll - Painter's own previews and names.
        The wheel moves through them (and puts each in hand), a click or Q
        again keeps it, Esc puts the old one back."""
        if self.ring is not None:
            self.ring.close()
            return
        self.ring = BrushScroll(self, self.mouse)

    def open_pie(self) -> None:
        """W: every tool and action at the cursor."""
        actions = [("undo", "arrow-u-up-left", "Undo", lambda: self.undo()),
                   ("redo", "arrow-u-up-right", "Redo", lambda: self.undo(True)),
                   ("picker", "palette", "Colour", lambda: self.open_picker_at(QtGui.QCursor.pos())),
                   ("paste", "clipboard-text", "Paste image", self.paste),
                   ("pin", "push-pin", "Pin to screen", self.pin),
                   ("ocr", "text-aa", "Copy text (OCR)", self.ocr),
                   ("save", "floppy-disk", "Save", self.save),
                   ("copy", "copy", "Copy", self.copy_and_close)]
        run = {a[0]: a[3] for a in actions}
        chosen = set(store.get("pie_items") or [])
        items = [(k, n, lambda p, r, i=i: _icon_tile(p, r, i)) for k, i, n in TOOLS] + \
                [(k, n, lambda p, r, i=i: _icon_tile(p, r, i)) for k, i, n, _f in actions]
        if chosen:
            items = [it for it in items if it[0] in chosen]
        self._ring(items, self.tool, lambda k: run[k]() if k in run else self.set_tool(k), radius=128, tile=21)

    def _ring(self, items, current, on_pick, radius, tile) -> None:
        if self.ring is not None:
            self.ring.close()
            return
        self.ring = Ring(self, self.mouse, items, current, on_pick, radius, tile)
        self.ring.destroyed.connect(lambda: setattr(self, "ring", None))

    def open_picker_at(self, at: QtCore.QPoint) -> None:
        """The palette right under the cursor (middle mouse by default)."""
        from .colorpicker import ColorPicker
        if getattr(self, "pinned_picker", None) is not None:      # pinned: that one, no second palette
            self.pinned_picker.raise_()
            return
        picker = ColorPicker(self, self.color)
        picker.setStyleSheet(theme.STYLE + picker.styleSheet())
        picker.picked.connect(self.set_color)
        size = picker.sizeHint()
        geo = self.screen().geometry()
        x = min(max(at.x() - size.width() // 2, geo.left()), geo.right() - size.width())
        y = min(max(at.y() - 20, geo.top()), geo.bottom() - size.height())
        picker.move(x, y)
        picker.show()

    # ------------------------------------------------------------ images in
    MARKS_MIME = "application/x-leadtool-marks"

    def copy_marks(self) -> None:
        """Ctrl+C with marks picked: they are copied (as marks for Ctrl+V here,
        as a picture for any other app)."""
        clones = [m.clone() for m in self.shapes if m in self.picked]
        if not clones:
            return
        box = QtCore.QRectF()
        for m in clones:
            box = box.united(m.bounds())
        dpr = self.base.devicePixelRatio()
        image = QtGui.QImage(max(1, int(box.width() * dpr)), max(1, int(box.height() * dpr)),
                             QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(image)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.scale(dpr, dpr)
        p.translate(-box.topLeft())
        for m in clones:
            m.paint(p, self.base)
        p.end()
        mark_id = store.new_id()
        self.app.mark_clip = (mark_id, clones)
        mime = QtCore.QMimeData()
        mime.setImageData(image)
        mime.setData(self.MARKS_MIME, mark_id.encode())
        QtWidgets.QApplication.clipboard().setMimeData(mime)
        self.app.toast(f"Copied {len(clones)} mark{'s' if len(clones) > 1 else ''}")

    def paste(self) -> None:
        """Ctrl+V: copied marks / a picture come in on a NEW layer, picked -
        move, scale (corners), flip (H), warp (U) right away; Ctrl+Z takes it back."""
        mime = QtWidgets.QApplication.clipboard().mimeData()
        clip = getattr(self.app, "mark_clip", None)
        if clip and mime.hasFormat(self.MARKS_MIME) and bytes(mime.data(self.MARKS_MIME)).decode() == clip[0]:
            self.push_undo()
            self.add_layer(undo=False)
            fresh = [m.clone() for m in clip[1]]
            for m in fresh:
                m.layer = self.layer_id
                m.move(20, 20)                          # beside the original, as Photoshop does
            self.shapes += fresh
            self.picked = fresh
            self.set_tool("select")
            self.picked = fresh
            self.touch()
            self.update()
            return
        image = None
        if self.report is not None and (mime.hasImage() or mime.hasUrls()):
            got = QtGui.QImage(mime.imageData()) if mime.hasImage() else QtGui.QImage()
            if got.isNull() and mime.hasUrls():
                got = next((QtGui.QImage(u.toLocalFile()) for u in mime.urls()
                            if u.isLocalFile() and not QtGui.QImage(u.toLocalFile()).isNull()), QtGui.QImage())
            if not got.isNull():
                self._report_add(got)                       # next in the row, not on top of everything
                return
        if mime.hasImage():
            image = QtGui.QPixmap.fromImage(QtGui.QImage(mime.imageData()))
        elif mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    image = QtGui.QPixmap(url.toLocalFile())
                    if not image.isNull():
                        break
        if image is not None and not image.isNull():
            self.add_image(image, self.region.center())

    def add_image(self, pixmap: QtGui.QPixmap, center: QtCore.QPointF) -> None:
        """Another picture beside / over this one - "how it should look" - on its own layer."""
        self.push_undo()
        self.add_layer(undo=False)
        dpr = self.base.devicePixelRatio()
        w, h = pixmap.width() / dpr, pixmap.height() / dpr
        k = min(1.0, self.region.width() * 0.6 / max(1, w), self.region.height() * 0.6 / max(1, h))
        s = Shape("image")
        s.layer = self._draw_layer_id()
        s.image = pixmap
        s.rect = QtCore.QRectF(center.x() - w * k / 2, center.y() - h * k / 2, w * k, h * k)
        self.shapes.append(s)
        self.selected = s
        self.set_tool("select")
        self.update()

    def dragEnterEvent(self, e):                                 # noqa: N802
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):                                      # noqa: N802
        if self.state != "edit":
            return
        mime = e.mimeData()
        pixmap = None
        if mime.hasImage():
            pixmap = QtGui.QPixmap.fromImage(QtGui.QImage(mime.imageData()))
        for url in mime.urls() if pixmap is None else ():
            if url.isLocalFile():
                pixmap = QtGui.QPixmap(url.toLocalFile())
                if not pixmap.isNull():
                    break
        if pixmap is not None and not pixmap.isNull():
            self.add_image(pixmap, e.position())
            e.acceptProposedAction()

    # ------------------------------------------------------------ results
    def compose(self, scale: float = 0.0) -> QtGui.QImage:
        self._finish_text()
        dpr = scale or self.base.devicePixelRatio()
        r = self.region
        image = QtGui.QImage(max(1, round(r.width() * dpr)), max(1, round(r.height() * dpr)),
                             QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.GlobalColor.black)
        p = QtGui.QPainter(image)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.scale(dpr, dpr)
        p.translate(-r.topLeft())
        self._draw_stack(p, dpr, live=False)
        p.end()
        return image

    # ------------------------------------------------------------ report
    def resizeEvent(self, e):                                    # noqa: N802
        super().resizeEvent(e)
        if self.report is None or self.state != "edit" or not hasattr(self, "report_bar"):
            return
        self._new_canvas()
        self._report_fit(QtCore.QRectF(self.region))

    def _new_canvas(self) -> None:
        dpr = self.devicePixelRatioF()
        canvas = QtGui.QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        canvas.fill(QtCore.Qt.GlobalColor.transparent)
        canvas.setDevicePixelRatio(dpr)
        self.base, self._small_image = canvas, canvas.toImage()

    def _screen_changed(self, _screen=None) -> None:
        """Dragged onto another monitor: its scale may differ - redraw for it;
        bigger than that monitor - it shrinks to fit (the report refits inside)."""
        if self.drag and self.drag[0] == "window":
            return                                      # still being dragged: settled when the button comes up
        # nothing is re-laid out when it is let go (that was the jerk): the window just
        # stays where it was dropped; only a monitor with another scale gets a new canvas
        if abs(self.devicePixelRatioF() - self.base.devicePixelRatio()) > 1e-6:
            self._new_canvas()
            self.touch()
            self.update()

    def report_setup(self) -> None:
        """A new report: a template-sized empty area, a layer for the screenshots."""
        from . import report as rp
        self.layers = [lay.new_layer(lay.BG, "Background"), lay.new_layer("l1", "Layer 1")]
        self.layer_id = "l1"
        w = min(self.width() * 0.6, 1400.0)
        h = w * 851 / 2468
        self.region = QtCore.QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        self.report.setdefault("stage", rp.STAGES[0])
        self.report["h"] = h / (1 + rp.BAND)
        self.report["top"] = self.region.top()
        self.report["empty"] = True
        self._enter_edit()
        self.report_bar = rp.ReportBar(self)
        self.report_bar.show()
        if self.windowHandle() is not None:
            self.windowHandle().screenChanged.connect(self._screen_changed)
        self._report_place()

    def restore_report(self, session) -> None:
        self.shapes = [s.clone() for s in session["shapes"]]
        self.layers = lay.copy_layers(session["layers"])
        self.layer_id = session["layer_id"]
        self.region = QtCore.QRectF(session["region"])
        if self.report.get("bg"):
            self._refill_base()
        self._report_place()

    def _report_place(self) -> None:
        self._zoom_button()
        bar = getattr(self, "report_bar", None)
        if bar is not None:
            bar.adjustSize()
            w = max(980, bar.sizeHint().width())
            bar.resize(int(w), bar.sizeHint().height())
            # tied to the report, not to the screen: it travels with it
            vr = self._vrect(self.region)
            x = vr.left() + (vr.width() - w) / 2
            x = min(max(4, x), self.width() - w - 4)
            bar.move(int(x), int(max(4, vr.top() - bar.height() - 34)))
        self._place_panel()
        self.touch()
        self.update()

    def report_shot(self, same: bool = False) -> None:
        """Add a screenshot: the report steps aside, you pick the area (or the
        same area again), it lands at the end of the row."""
        self._finish_text()
        self.hide()                                     # out of the picture before the screen is frozen
        QtCore.QTimer.singleShot(180, lambda: self.app.capture_for(
            self._report_add, repeat=bool(same and store.get("last_area"))))

    def _report_add(self, image) -> None:
        from . import report as rp
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        if image is None or image.isNull():
            return
        self.push_undo()
        shots = [m for m in self.shapes if m.shot]
        first = bool(self.report.get("empty") or not shots)
        if first:
            h = min(self.height() * 0.62, image.height() / self.base.devicePixelRatio())
            left, top = self.region.left(), self.region.top()
            x = left
            self.report["k"] = h / image.height()             # screen units per pixel: the first shot sets it
        else:
            h, top = self.report["h"], self.report["top"]
            left = self.region.left()
            x = max(m.bounds().right() for m in shots) + h * 0.006
        # every shot at the same pixel scale, top-aligned: a small one stays small, the background
        # shows under it; a taller one makes the area taller (crop it by the frame)
        sh = image.height() * self.report.get("k", h / image.height())    # its own scale, never squeezed (a tall one grows the area)
        w = image.width() * sh / image.height()
        s = Shape("image")
        pm = QtGui.QPixmap.fromImage(image)
        pm.setDevicePixelRatio(1.0)
        s.image, s.raster, s.shot = pm, True, True
        n = 1 + sum(1 for x in self.layers if x["id"].startswith("s") and x["id"][1:].isdigit())
        at = 1 + sum(1 for x in self.layers if x["id"] == "shots" or (x["id"].startswith("s") and x["id"][1:].isdigit()))
        self.layers.insert(at, lay.new_layer(f"s{n}", f"Screenshot {n}"))   # each shot its own layer
        s.layer = f"s{n}"
        if self.layers_panel is not None and self.layers_panel.isVisible():
            self.layers_panel.sync()
        s.rect = QtCore.QRectF(x, top, w, sh)
        self.shapes.append(s)
        self.report.update(h=h, top=top, empty=False)
        tall = max([h, sh] + [m.bounds().bottom() - top for m in self.shapes if m.shot])
        bottom = top + tall + self._band()
        right = x + w
        if not first:                                   # a stretched (cropped) area keeps what you gave it
            bottom, right = max(self.region.bottom(), bottom), max(self.region.right(), right)
        self._report_fit(QtCore.QRectF(left, top, right - left, bottom - top))

    def _report_fit(self, region) -> None:
        """The whole report on screen, centred (shrunk when it grows too wide):
        everything on it scales along."""
        # the monitor the report is on, in this window's units (the window may sit across monitors)
        here = QtGui.QGuiApplication.screenAt(self.mapToGlobal(self.region.center().toPoint())) or self.screen()
        mon = here.availableGeometry() if here is not None else self.geometry()
        avail = QtCore.QRectF(QtCore.QPointF(self.mapFromGlobal(mon.topLeft())), QtCore.QSizeF(mon.size()))
        avail = avail.intersected(QtCore.QRectF(self.rect())) if avail.intersects(QtCore.QRectF(self.rect())) \
            else QtCore.QRectF(self.rect())
        avail = avail.adjusted(40, 110, -130, -40)
        f = min(1.0, avail.width() / max(1.0, region.width()), avail.height() / max(1.0, region.height()))
        size = region.size() * f
        tl = QtCore.QPointF(avail.center().x() - size.width() / 2, avail.center().y() - size.height() / 2)
        t = QtGui.QTransform.fromTranslate(-region.left(), -region.top()) * QtGui.QTransform.fromScale(f, f) * \
            QtGui.QTransform.fromTranslate(tl.x(), tl.y())
        for m in self.shapes:
            if m.xform.isIdentity() and abs(f - 1.0) < 1e-9:
                m.move(t.dx(), t.dy())                  # only moved: keep it plain
            else:
                m.xform = m.xform * t
        self.region = QtCore.QRectF(tl, size)
        self.report["h"] = self.report["h"] * f
        self.report["k"] = self.report.get("k", 1.0) * f
        self.report["top"] = tl.y()
        self.picked = []
        self._report_place()

    def report_background(self, color) -> None:
        """The whole report behind the screenshots in one colour (picked with
        the eyedropper or the palette)."""
        self.report["bg"] = QtGui.QColor(color).name()
        self.layer(lay.BG)["fill"] = self.report["bg"]
        self._refill_base()
        self.touch()
        self.update()

    def pick_background(self, at: QtCore.QPoint) -> None:
        """The palette for the report's background, live; one Ctrl+Z takes it back."""
        from .colorpicker import ColorPicker
        from . import report as rp
        self.push_undo()
        picker = ColorPicker(self, QtGui.QColor(self.report.get("bg") or rp.BG))
        picker.setStyleSheet(theme.STYLE + picker.styleSheet())
        picker.picked.connect(self.report_background)
        picker.move(at)
        picker.show()

    def _refill_base(self) -> None:
        self.__dict__.get("_lcache", {}).pop(lay.BG, None)

    def _band(self) -> float:
        """The band's height in screen units. In the PNG's pixels: 7.5 % of the screenshot row
        + 20 px, never under 56 or over 150 - a 1000 px row gets ~95 px, a 4K row 150, a small
        500 px one 57 (small shots got a fat band). It does not grow with the frame."""
        from . import report as rp
        h = self.report.get("h") or self.region.height() / (1 + rp.BAND)
        k = self._report_scale(for_band=True)
        px = min(150.0, max(56.0, 0.075 * h * k + 20.0))
        return px / k

    def _report_scale(self, for_band: bool = False) -> float:
        """Pixels per screen unit for the file: the screenshots at their full size."""
        k = self.base.devicePixelRatio()
        for m in self.shapes:
            if m.shot and m.image is not None and m.rect.height() > 0:
                x = m.xform
                k = max(k, m.image.height() / (m.rect.height() * math.hypot(x.m21(), x.m22())))
        if for_band:
            return k
        return min(k, 16000 / max(1.0, self.region.width()), 16000 / max(1.0, self.region.height()))

    def report_save(self, ask: bool = False) -> None:
        import re
        folder = store.get("report_dir") or ""
        if ask or not folder or not os.path.isdir(folder):
            folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Where reports go", folder or os.path.expanduser("~"))
            if not folder:
                return
            store.put("report_dir", folder)
        m = re.search(r"[A-Za-z]+-\d+", self.report.get("task", ""))       # the first task number
        name = m.group(0).upper() if m else (self.report.get("asset") or "report")
        path = os.path.join(folder, name + ".png")
        n = 2
        while os.path.exists(path) and path != self.report.get("saved"):
            path = os.path.join(folder, f"{name} ({n}).png")
            n += 1
        image = self.compose(self._report_scale())
        image.save(path)
        self.report["saved"] = path
        from .report import remember_preset
        remember_preset(self.report.get("task", ""), self.report.get("asset", ""))   # for the Recent list
        self.app.toast(f"Saved {os.path.basename(path)}  {image.width()}×{image.height()}", path)

    # ------------------------------------------------------------ layers
    def layer(self, lid):
        return next((x for x in self.layers if x["id"] == lid), None)

    def _marks_layer(self, s) -> str:
        """The layer a mark lives on ("" or a gone layer = the first layer of marks)."""
        ids = [x["id"] for x in self.layers]
        if s.layer in ids:
            return s.layer
        return next((i for i in ids if i != lay.BG), lay.BG)

    def _shown(self, s) -> bool:
        layer = self.layer(self._marks_layer(s))
        return layer is None or layer.get("visible", True)

    def _layer_image(self, layer, dpr: float) -> QtGui.QImage:
        """A layer's own picture (the screenshot or transparent, its marks on
        it, then its adjustments) - cached until something changes."""
        r = self.region
        mine = [m for m in self.shapes if self._marks_layer(m) == layer["id"]]
        # only what changed is redrawn: a layer's key is ITS marks' state, not "something changed somewhere"
        key = (r.getRect(), dpr, self._layer_sig(layer))
        cache = self.__dict__.setdefault("_lcache", {})
        got = cache.get(layer["id"])
        if got is not None and got[0] == key:
            return got[1]
        if layer["id"] == lay.BG and self.report is not None:   # a report: its own background colour
            from . import report as rp
            image = QtGui.QImage(max(1, int(r.width() * dpr)), max(1, int(r.height() * dpr)),
                                 QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QtGui.QColor(self.report.get("bg") or rp.BG))
        elif layer["id"] == lay.BG:
            bd = self.base.devicePixelRatio()
            image = self.base.copy(QtCore.QRect(round(r.x() * bd), round(r.y() * bd),
                                                round(r.width() * bd), round(r.height() * bd))).toImage()
            if abs(dpr - bd) > 1e-6:                    # a bigger export: the same picture, scaled
                image = image.scaled(max(1, int(r.width() * dpr)), max(1, int(r.height() * dpr)),
                                     QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                                     QtCore.Qt.TransformationMode.SmoothTransformation)
            image = image.convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        else:
            image = QtGui.QImage(max(1, int(r.width() * dpr)), max(1, int(r.height() * dpr)),
                                 QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QtCore.Qt.GlobalColor.transparent)
        image.setDevicePixelRatio(dpr)
        if mine:
            # the finished marks, painted once per change - not once per mouse move
            p = QtGui.QPainter(image)
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            p.translate(-r.topLeft())
            for m in mine:
                m.paint(p, self.base)
            p.end()
        cache[layer["id"]] = (key, image)
        return image

    @staticmethod
    def _mark_sig(m) -> tuple:
        x = m.xform
        # by content, not by object: Ctrl+Z brings back copies, and they must hit the cache
        return (m.kind, len(m.points), m.points[0].toTuple() if m.points else None,
                m.points[-1].toTuple() if m.points else None,
                m.rect.getRect(), m.width, m.color.rgba(), m.text, id(m.warp), m.number, m.opacity, m.flow,
                m.angle, m.erase, m.font, m.box, m.outline, id(m.image), id(m._render),
                tuple(Overlay._mark_sig(c) for c in m.cuts),
                (x.m11(), x.m12(), x.m13(), x.m21(), x.m22(), x.m23(), x.m31(), x.m32(), x.m33()))

    def _layer_sig(self, layer) -> tuple:
        mine = tuple(self._mark_sig(m) for m in self.shapes if self._marks_layer(m) == layer["id"])
        return (layer["id"], layer.get("fill"), layer.get("visible", True), layer.get("opacity", 1.0), layer.get("blend"),
                layer.get("kind", ""), tuple(sorted(layer["adj"].items())) if layer.get("kind") else (), mine)

    def _stack_sig(self, layers) -> tuple:
        return tuple(self._layer_sig(x) for x in layers)

    def _composite(self, layers, dpr: float) -> QtGui.QImage:
        """These layers flattened, bottom to top. Every step is cached on its
        own: a change on a layer redoes that layer and the ones above it, never
        the filters under it (the warp and Ctrl+Z used to wait for those)."""
        r = self.region
        cache = self.__dict__.setdefault("_ccache", {})
        key = (r.getRect(), dpr)
        acc = None
        for k, layer in enumerate(layers):
            key = key + (self._layer_sig(layer),)
            got = cache.get(k)
            if got is not None and got[0] == key:
                acc = got[1]
                continue
            base = acc
            acc = QtGui.QImage(max(1, int(r.width() * dpr)), max(1, int(r.height() * dpr)),
                               QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            acc.setDevicePixelRatio(dpr)
            if base is None:
                acc.fill(QtGui.QColor("#1e1e1e"))
            else:
                acc.fill(QtCore.Qt.GlobalColor.transparent)
            p = QtGui.QPainter(acc)
            if base is not None:
                p.drawImage(0, 0, base)
            if layer.get("visible", True):
                if layer.get("kind"):                       # adjustment: what is under it, re-coloured
                    p.setOpacity(layer.get("opacity", 1.0))
                    p.drawImage(0, 0, lay.adjust(base if base is not None else acc, layer["adj"]))
                else:
                    if layer["id"] != lay.BG:
                        p.setOpacity(layer.get("opacity", 1.0))
                        p.setCompositionMode(lay.BLENDS.get(layer.get("blend", "Normal"),
                                                            lay.CM.CompositionMode_SourceOver))
                    p.drawImage(0, 0, self._layer_image(layer, dpr))
            p.end()
            cache[k] = (key, acc)
        if acc is None:
            acc = QtGui.QImage(max(1, int(r.width() * dpr)), max(1, int(r.height() * dpr)),
                               QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            acc.fill(QtGui.QColor("#1e1e1e"))
            acc.setDevicePixelRatio(dpr)
        return acc

    def _draw_stack(self, p, dpr: float, live: bool = True) -> None:
        self._draw_layers(p, dpr, live)
        if self.report is not None:                     # the report's band: over everything, the whole width
            from . import report as rp
            rp.paint_band(p, self.region, self._band(),
                          self.report.get("task", ""), self.report.get("asset", ""), self.report.get("stage", ""))

    def _draw_layers(self, p, dpr: float, live: bool = True) -> None:
        """Everything, flattened. While a mark is being drawn: the layers under
        its layer come from the cache, its layer gets the live mark, the layers
        above go on top (their filters wait for the button to come up)."""
        r = self.region
        lid = None
        if live and self.current is not None:
            lid = self._marks_layer(self.current)
        elif live and self.drag and self.drag[0] in ("warp", "move", "xf") and self.picked:
            # a drag: the lowest layer being changed - the filters above it wait for the button to come up
            ids = [x["id"] for x in self.layers]
            lid = min((self._marks_layer(m) for m in self.picked), key=lambda x: ids.index(x) if x in ids else 0)
        if lid is None:
            p.drawImage(r.topLeft(), self._composite(self.layers, dpr))
            return
        i = next((k for k, x in enumerate(self.layers) if x["id"] == lid), len(self.layers) - 1)
        p.drawImage(r.topLeft(), self._composite(self.layers[:i], dpr))
        for layer in self.layers[i:]:
            if not layer.get("visible", True) or layer.get("kind"):
                continue
            image = self._layer_image(layer, dpr)
            if layer["id"] == lid and self.current is not None:
                image = image.copy()                        # the live stroke on top (an eraser cuts this copy)
                image.setDevicePixelRatio(dpr)
                q = QtGui.QPainter(image)
                q.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
                q.translate(-r.topLeft())
                self.current.paint(q, self.base)
                q.end()
            p.save()
            if layer["id"] != lay.BG:
                p.setOpacity(layer.get("opacity", 1.0))
                p.setCompositionMode(lay.BLENDS.get(layer.get("blend", "Normal"), lay.CM.CompositionMode_SourceOver))
            p.drawImage(r.topLeft(), image)
            p.restore()

    def _attach_cut(self, eraser) -> bool:
        """An eraser stroke is given to every mark under it (same layer): what
        was erased then moves, turns, scales and warps with the mark (moved strokes left their erased bits behind)."""
        lid = self._marks_layer(eraser)
        box = eraser.bounds()
        hit = [m for m in self.shapes if not m.erase and self._marks_layer(m) == lid and m.bounds().intersects(box)]
        if not hit:
            return False
        for m in hit:
            cut = eraser.clone()
            cut.cuts = []
            if not m.xform.isIdentity():                # into the mark's own frame
                cut.xform = m.xform.inverted()[0]
            m.cuts = m.cuts + [cut]
        self.touch()
        return True

    def _set_selection(self, poly) -> None:
        self.sel_poly = poly
        if poly is None:
            if self.sel_bar is not None:
                self.sel_bar.hide()
            self.update()
            return
        if self.sel_bar is None:                        # Fill / Erase under the selection
            bar = self.sel_bar = QtWidgets.QWidget(self)
            bar.setObjectName("ltSelBar")
            bar.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
            bar.setStyleSheet(theme.STYLE + "#ltSelBar { background: #262626; border: 1px solid #141414; border-radius: 8px; }")
            bar.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            row = QtWidgets.QHBoxLayout(bar)
            row.setContentsMargins(5, 4, 5, 4)
            row.setSpacing(4)
            for text, tip, slot in (("Fill", "Fill with the current colour  (Alt+Backspace)", self.fill_selection),
                                    ("Erase", "Erase inside  (Delete)", self.erase_selection),
                                    ("✕", "Drop the selection  (Esc)", lambda: self._set_selection(None))):
                b = QtWidgets.QPushButton(text)
                b.setToolTip(tip)
                b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
                b.clicked.connect(lambda _c=False, f=slot: f())
                row.addWidget(b)
        bar = self.sel_bar
        bar.adjustSize()
        b = self._vrect(poly.boundingRect())
        y = b.bottom() + 8 if b.bottom() + 8 + bar.height() < self.height() else b.top() - bar.height() - 8
        bar.move(int(min(max(4, b.center().x() - bar.width() / 2), self.width() - bar.width() - 4)), int(y))
        bar.show()
        bar.raise_()
        self.update()

    def set_sel_mode(self, mode: str) -> None:
        self.sel_mode = mode
        store.data()["sel_mode"] = mode
        self.set_tool("lasso")

    def fill_selection(self) -> None:
        if self.sel_poly is None:
            return
        self.push_undo()
        s = Shape("poly", self.color, 1, 1.0)
        s.points = list(self.sel_poly)
        s.layer = self._draw_layer_id()
        self.shapes.append(s)
        self.touch()
        self.update()

    def erase_selection(self) -> None:
        """Delete: what is inside goes - out of the marks / screenshots it covers
        (it travels with them, like the eraser)."""
        if self.sel_poly is None:
            return
        self.push_undo()
        s = Shape("poly", QtGui.QColor(0, 0, 0), 1, 1.0)
        s.points = list(self.sel_poly)
        s.erase = True
        s.layer = self._draw_layer_id()                 # the current layer only, as in Photoshop
        if not self._attach_cut(s):
            self.shapes.append(s)
        self.touch()
        self.update()

    def _draw_layer_id(self) -> str:
        """Where a new mark goes: the current layer - or, on an adjustment
        layer, the nearest layer of marks under it."""
        i = next((k for k, x in enumerate(self.layers) if x["id"] == self.layer_id), 0)
        for layer in reversed(self.layers[:i + 1]):
            if not layer.get("kind"):
                return layer["id"]
        return lay.BG

    def add_layer(self, undo: bool = True, kind: str = "") -> None:
        if undo:
            self.push_undo()
        n = 1 + max([int(x["id"][1:]) for x in self.layers if x["id"][1:].isdigit()] or [0])
        new = lay.new_layer(f"l{n}", lay.KINDS[kind][0] if kind else f"Layer {n}", kind)
        at = next((i for i, x in enumerate(self.layers) if x["id"] == self.layer_id), len(self.layers) - 1)
        self.layers.insert(at + 1, new)                    # right above the current one
        self.layer_id = new["id"]
        self._layers_changed()

    def delete_layer(self) -> None:
        if self.layer_id == lay.BG or (not (self.layer(self.layer_id) or {}).get("kind")
                                       and len([x for x in self.layers if x["id"] != lay.BG and not x.get("kind")]) <= 1):
            return                                          # the screenshot and the last layer of marks stay
        self.push_undo()
        gone = self.layer_id
        self.shapes = [m for m in self.shapes if self._marks_layer(m) != gone]
        i = next(i for i, x in enumerate(self.layers) if x["id"] == gone)
        del self.layers[i]
        self.layer_id = self.layers[max(1, i - 1)]["id"] if len(self.layers) > 1 else lay.BG
        self.picked = []
        self._layers_changed()

    def move_layer(self, step: int) -> None:
        i = next((i for i, x in enumerate(self.layers) if x["id"] == self.layer_id), None)
        if i is None or self.layer_id == lay.BG or not 1 <= i + step < len(self.layers):
            return
        self.push_undo()
        self.layers[i], self.layers[i + step] = self.layers[i + step], self.layers[i]
        self._layers_changed()

    def move_layer_to(self, lid: str, slot: int) -> None:
        """A layer dragged in the panel: slot = its place counted from the bottom (1 = right over the screenshot)."""
        i = next((k for k, x in enumerate(self.layers) if x["id"] == lid), None)
        if i is None or lid == lay.BG:
            return
        to = slot if slot <= i else slot - 1
        to = max(1, min(len(self.layers) - 1, to))
        if to == i:
            return
        self.push_undo()
        layer = self.layers.pop(i)
        self.layers.insert(to, layer)
        self.layer_id = lid
        self._layers_changed()

    def toggle_layer(self, lid: str) -> None:
        layer = self.layer(lid)
        if layer is not None:
            layer["visible"] = not layer.get("visible", True)
            self.picked = [m for m in self.picked if self._shown(m)]
            self._layers_changed()

    def marks_to_layer(self) -> None:
        if not self.picked:
            return
        self.push_undo()
        for m in self.picked:
            m.layer = self._draw_layer_id()
        self._layers_changed()

    def _layers_changed(self) -> None:
        self.touch()
        if self.layers_panel is not None:
            self.layers_panel.sync()
            self._place_layers()
        self.update()

    def toggle_layers_panel(self) -> None:
        """F7 (Photoshop's) or the panel's button: the layers beside the capture."""
        if self.layers_panel is None:
            self.layers_panel = lay.LayersPanel(self)
        if self.layers_panel.isVisible():
            self.layers_panel.hide()
        else:
            self.layers_panel.sync()
            self._place_layers()
            self.layers_panel.show()
            self.layers_panel.raise_()
        self.setFocus()

    def _place_layers(self) -> None:
        lp = self.layers_panel
        if lp is None:
            return
        lp.setFixedHeight(lp.sizeHint().height())
        pos = store.get("layers_pos")
        if store.get("layers_pin") and pos:              # pinned: where it was put
            lp.move(max(0, min(self.width() - lp.width(), pos[0])), max(0, min(self.height() - lp.height(), pos[1])))
            return
        r, tools = self._vrect(self.region), self.panel.geometry()
        x = r.left() - lp.width() - 8 if tools.left() >= r.center().x() else r.right() + 8
        if x < 4 or x + lp.width() > self.width() - 4:            # no room on that side: next to the tools
            x = tools.left() - lp.width() - 6 if tools.left() - lp.width() - 6 > 4 else tools.right() + 6
        y = max(4, min(r.top(), self.height() - lp.height() - 4))
        lp.move(int(x), int(y))

    # ------------------------------------------------------------ warp (U)
    def start_warp(self) -> None:
        """U: the picked marks become one picture with a 4x4 mesh over it -
        drag a point, or drag inside to bend the surface. Enter / U / Esc ends."""
        if not self.picked or self.state != "edit":
            return
        if len(self.picked) == 1 and self.picked[0].kind == "image" and self.picked[0].xform.isIdentity():
            target = self.picked[0]
            if not target.warp:
                self.push_undo()
                target.warp = Shape.identity_warp()
            self.warping = target
            self.update()
            return
        self.push_undo()
        dpr = self.base.devicePixelRatio()
        box = QtCore.QRectF()
        for m in self.picked:
            box = box.united(m.bounds())
        box = box.adjusted(-2, -2, 2, 2)
        image = QtGui.QImage(max(1, int(box.width() * dpr)), max(1, int(box.height() * dpr)),
                             QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(image)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.scale(dpr, dpr)
        p.translate(-box.topLeft())
        order = [m for m in self.shapes if m in self.picked]
        for m in order:
            m.paint(p, self.base)
        p.end()
        flat = Shape("image")
        flat.image = QtGui.QPixmap.fromImage(image)
        flat.rect = box
        flat.raster = True
        flat.warp = Shape.identity_warp()
        flat.layer = self._marks_layer(order[0])
        at = self.shapes.index(order[-1])
        self.shapes.insert(at + 1, flat)
        self.shapes = [m for m in self.shapes if m not in order]
        self.picked = [flat]
        self.warping = flat
        self.touch()
        self.update()

    def end_warp(self) -> None:
        self.warping = None
        self.update()

    def _warp_local(self, pos):
        w = self.warping
        local = w.xform.inverted()[0].map(pos) if not w.xform.isIdentity() else pos
        r = w.rect.normalized()
        return ((local.x() - r.x()) / max(1.0, r.width()), (local.y() - r.y()) / max(1.0, r.height()))

    def _warp_points(self):
        w = self.warping
        r = w.rect.normalized()
        return [w.xform.map(QtCore.QPointF(r.x() + x * r.width(), r.y() + y * r.height())) for x, y in w.warp]

    def _warp_press(self, pos) -> bool:
        w = self.warping
        if w is None or w not in self.shapes:
            self.warping = None
            return False
        for i, pt in enumerate(self._warp_points()):
            if abs(pt.x() - pos.x()) <= 7 and abs(pt.y() - pos.y()) <= 7:
                self.push_undo()
                self.drag = ("warp", (i, pos, list(w.warp)))
                return True
        if w.hit(pos):                                      # inside: bend the surface where you grab it
            n = 16
            best, uv = None, (0.5, 0.5)
            for j in range(n + 1):
                for i in range(n + 1):
                    pt = w.xform.map(w.warp_at(i / n, j / n))
                    d = (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2
                    if best is None or d < best:
                        best, uv = d, (i / n, j / n)
            self.push_undo()
            self.drag = ("warp", (uv, pos, list(w.warp)))
            return True
        self.end_warp()                                     # a click outside ends the warp
        return False

    def _warp_move(self, pos) -> None:
        w = self.warping
        what, start, before = self.drag[1]
        a, b = self._warp_local(start), self._warp_local(pos)
        d = (b[0] - a[0], b[1] - a[1])
        if isinstance(what, int):
            pts = list(before)
            pts[what] = (before[what][0] + d[0], before[what][1] + d[1])
        else:
            u, v = what
            bu = ((1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3)
            bv = ((1 - v) ** 3, 3 * v * (1 - v) ** 2, 3 * v * v * (1 - v), v ** 3)
            wts = [bu[i] * bv[j] for j in range(4) for i in range(4)]
            norm = sum(x * x for x in wts) or 1.0
            pts = [(c[0] + d[0] * k / norm, c[1] + d[1] * k / norm) for c, k in zip(before, wts)]
        w.warp = pts
        self.touch()

    def _paint_warp(self, p) -> None:
        w = self.warping
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        n = 24
        for k in range(4):                                  # the mesh lines through the controls
            t = k / 3
            p.drawPolyline(QtGui.QPolygonF([w.xform.map(w.warp_at(i / n, t)) for i in range(n + 1)]))
            p.drawPolyline(QtGui.QPolygonF([w.xform.map(w.warp_at(t, i / n)) for i in range(n + 1)]))
        p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1, QtCore.Qt.PenStyle.DotLine))
        pts = self._warp_points()
        for j in range(4):                                  # the control net
            p.drawPolyline(QtGui.QPolygonF(pts[j * 4:j * 4 + 4]))
            p.drawPolyline(QtGui.QPolygonF(pts[j::4]))
        p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1))
        p.setBrush(QtGui.QColor("#ffffff"))
        for pt in pts:
            p.drawEllipse(pt, 4, 4)

    def touch(self) -> None:
        """Something about the marks changed: the cached layer is redrawn."""
        self._version += 1
        lp = self.__dict__.get("layers_panel")
        if lp is not None and lp.isVisible():
            lp._thumbs.start()                              # the thumbnails catch up a moment later

    def _base_crop(self) -> QtGui.QImage:
        dpr = self.base.devicePixelRatio()
        r = self.region
        return self.base.copy(QtCore.QRect(round(r.x() * dpr), round(r.y() * dpr),
                                           round(r.width() * dpr), round(r.height() * dpr))).toImage()

    def _remember(self, image: QtGui.QImage) -> None:
        """History: the result + its clean base + the marks, to reopen later."""
        folder = store.history_dir()
        hid = self.entry_id or store.new_id()
        image.save(os.path.join(folder, hid + ".png"))
        self._base_crop().save(os.path.join(folder, hid + "_base.png"))
        marks = []
        for s in self.shapes:
            d = Shape.from_dict(s.to_dict())
            d.move(-self.region.x(), -self.region.y())
            marks.append(d.to_dict())
        with open(os.path.join(folder, hid + ".json"), "w", encoding="utf-8") as handle:
            json.dump({"shapes": marks, "layers": self.layers, "dpr": self.base.devicePixelRatio()}, handle)
        history = [h for h in store.get("history") if h.get("id") != hid]
        history.insert(0, {"id": hid, "created": datetime.datetime.now().isoformat(timespec="seconds")})
        for old in history[store.get("history_max"):]:
            for suffix in (".png", "_base.png", ".json"):
                try:
                    os.remove(os.path.join(folder, old["id"] + suffix))
                except OSError:
                    pass
        store.put("history", history[:store.get("history_max")])
        self.entry_id = hid

    def copy_and_close(self) -> None:
        if self.state != "edit":
            return
        if self.report is not None:                     # a report: copy, stay open
            self.app.toast("Report copied" if put_image(self.compose(self._report_scale())) else "Copy failed - try again")
            return
        image = self.compose()
        ok = put_image(image)
        self._remember(image)
        self.app.toast("Copied to clipboard" if ok else "The clipboard is busy (another program) - saved to History")
        self.close()

    def save(self, ask: bool = False) -> None:
        if self.state != "edit":
            return
        image = self.compose()
        name = datetime.datetime.now().strftime("LeadTool_%Y-%m-%d_%H-%M-%S.png")
        path = os.path.join(store.save_dir(), name)
        if ask:
            path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save screenshot", path, "PNG (*.png);;JPEG (*.jpg)")
            if not path:
                return
        image.save(path)
        QtWidgets.QApplication.clipboard().setImage(image)
        self._remember(image)
        self.app.toast(f"Saved and copied: {os.path.basename(path)}", path)
        self.close()

    def pin(self) -> None:
        if self.state != "edit":
            return
        from .pin import PinWindow
        image = self.compose()
        self._remember(image)
        top_left = self.mapToGlobal(self.region.topLeft().toPoint())
        self.close()
        self.app.keep(PinWindow(QtGui.QPixmap.fromImage(image), top_left))

    def ocr(self) -> None:
        if self.state != "edit":
            return
        from . import ocr
        text = ocr.recognize(self._base_crop())
        if text:
            QtWidgets.QApplication.clipboard().setText(text)
            self.app.toast(f"Text copied ({len(text)} chars)")
            self.close()
        else:
            self.app.toast("No text found")

    def _context_menu(self, at) -> None:
        menu = QtWidgets.QMenu(self)
        menu.addAction(theme.icon("copy"), "Copy  (Ctrl+C / Enter)", self.copy_and_close)
        menu.addAction(theme.icon("floppy-disk"), "Save  (Ctrl+S)", self.save)
        menu.addAction(theme.icon("floppy-disk"), "Save As...", lambda: self.save(ask=True))
        menu.addAction(theme.icon("push-pin"), "Pin to Screen  (Ctrl+P)", self.pin)
        menu.addAction(theme.icon("text-aa"), "Copy Text (OCR)  (Ctrl+T)", self.ocr)
        menu.addAction(theme.icon("clipboard-text"), "Paste Image  (Ctrl+V)", self.paste)
        menu.addSeparator()
        menu.addAction(theme.icon("x"), "Close  (Esc)", self.close)
        menu.exec(at)

    def closeEvent(self, e):                                     # noqa: N802
        if self.picking:
            self._stop_picking()
        if self.report is not None:                     # the report window opens where it was left
            g = self.geometry()
            store.data()["report_geometry"] = [g.x(), g.y(), g.width(), g.height()]
        if self.report is not None and getattr(self, "report_keep", True):    # the report waits for its next opening
            self._finish_text()
            self.app.report_session = {"report": dict(self.report), "shapes": [s.clone() for s in self.shapes],
                                       "layers": lay.copy_layers(self.layers), "layer_id": self.layer_id,
                                       "region": QtCore.QRectF(self.region)}
        store.save()
        self.closed.emit()
        super().closeEvent(e)


class _TextSession:
    """The text being typed: its shape, where the caret is, blink state."""

    def __init__(self, shape, caret: int):
        self.shape, self.caret, self.on = shape, caret, True


def _eyedropper_cursor() -> QtGui.QCursor:
    pixmap = QtGui.QPixmap.fromImage(theme.icon_image("eyedropper", 24, "#ffffff"))
    shadow = QtGui.QPixmap(26, 26)
    shadow.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(shadow)
    p.drawImage(2, 2, theme.icon_image("eyedropper", 24, "#000000"))
    p.drawPixmap(0, 0, pixmap)
    p.end()
    return QtGui.QCursor(shadow, 1, 24)                  # the tip of the dropper is the hot spot


class Panel(QtWidgets.QWidget):
    """The tools beside the selection: big buttons, one colour per group
    (the small grey ones read as nothing)."""
    BTN = 34
    ICON = 20

    def __init__(self, overlay: Overlay):
        super().__init__(overlay)
        self.o = overlay
        self.setObjectName("ltPanel")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.STYLE + "#ltPanel { background: #262626; border: 1px solid #141414; border-radius: 8px; }"
                           "#ltPanel QToolButton { border-radius: 6px; }")
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        col = QtWidgets.QVBoxLayout(self)
        col.setContentsMargins(5, 6, 5, 6)
        col.setSpacing(3)
        self.tools = {}
        names = {k: (i, n) for k, i, n in TOOLS}
        for group, color, kinds in GROUPS:
            grid = QtWidgets.QGridLayout()
            grid.setSpacing(3)
            for j, kind in enumerate(kinds):
                icon, name = names[kind]
                extra = f"  ·  {key_of('brushes')}: brushes" if kind == "brush" else ""
                b = self._button(icon, f"{name}  ({key_of(kind)}){extra}", lambda _c=False, k=kind: self.o.set_tool(k),
                                 checkable=True, color=color)
                if kind == "lasso":                        # Photoshop's tool group: hold for the other one
                    menu = QtWidgets.QMenu(b)
                    menu.setStyleSheet(theme.STYLE)
                    menu.addAction(theme.icon("selection", 16), "Rectangle Select", lambda: self.o.set_sel_mode("rect"))
                    menu.addAction(theme.icon("lasso", 16), "Lasso", lambda: self.o.set_sel_mode("lasso"))
                    b.setMenu(menu)
                    b.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.DelayedPopup)
                    b.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
                    b.customContextMenuRequested.connect(lambda _p, bb=b: bb.showMenu())
                    b.setStyleSheet("QToolButton::menu-indicator { image: none; }")
                    self.sel_btn, self.sel_color = b, color
                grid.addWidget(b, j // 2, j % 2)
                self.tools[kind] = b
            col.addLayout(grid)
            col.addSpacing(2)
        col.addWidget(self._line())
        # colours: current (click = palette) and the second one (Shift+X swaps), then the quick ones
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        self.color_btn = QtWidgets.QToolButton()
        self.color_btn.setFixedSize(self.BTN, self.BTN)
        self.color_btn.setToolTip("Colour  (right click on the picture, or C)")
        self.color_btn.clicked.connect(self.open_picker)
        row.addWidget(self.color_btn)
        self.color2_btn = QtWidgets.QToolButton()
        self.color2_btn.setFixedSize(26, 26)
        self.color2_btn.setToolTip("Second colour  (Shift+X swaps)")
        self.color2_btn.clicked.connect(self.o.swap_colors)
        row.addWidget(self.color2_btn, 0, QtCore.Qt.AlignmentFlag.AlignBottom)
        col.addLayout(row)
        sw = QtWidgets.QGridLayout()
        sw.setSpacing(3)
        for i, name in enumerate(store.get("colors")[:9]):
            b = QtWidgets.QToolButton()
            b.setFixedSize(26, 22)
            b.setToolTip(f"{name}  ({i + 1})")
            b.setStyleSheet(f"QToolButton {{ background: {name}; border: 1px solid #111; border-radius: 4px; }}"
                            f"QToolButton:hover {{ border-color: #fff; }}")
            b.clicked.connect(lambda _c=False, n=name: self.o.set_color(QtGui.QColor(n)))
            sw.addWidget(b, i // 3, i % 3)
        col.addLayout(sw)
        self.size_label = QtWidgets.QLabel()
        self.size_label.setProperty("role", "hint")
        self.size_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.size_label.setToolTip("Space + drag: size  ·  Ctrl + drag: flow (left/right), angle (up/down)")
        col.addWidget(self.size_label)
        # text / comment options
        self.font_btn = self._button("text-t", "Font", self._font_menu, color="#93b88d")
        self.box_btn = self._button("selection-background", "Text on a dark plate", self._toggle_box,
                                    checkable=True, color="#93b88d")
        trow = QtWidgets.QGridLayout()
        trow.setSpacing(3)
        trow.addWidget(self.font_btn, 0, 0)
        trow.addWidget(self.box_btn, 0, 1)
        self.outline_btn = QtWidgets.QToolButton()
        self.outline_btn.setFixedSize(self.BTN, self.BTN)
        self.outline_btn.setToolTip("Outline colour  ·  right click: no outline")
        self.outline_btn.clicked.connect(self._pick_outline)
        self.outline_btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.outline_btn.customContextMenuRequested.connect(lambda _p: self._set_outline(""))
        trow.addWidget(self.outline_btn, 1, 0)
        self.text_row = QtWidgets.QWidget()
        self.text_row.setLayout(trow)
        trow.setContentsMargins(0, 0, 0, 0)
        col.addWidget(self.text_row)
        # which stamp the stamp tool puts down
        from .shapes import STAMPS
        srow = QtWidgets.QGridLayout()
        srow.setSpacing(3)
        srow.setContentsMargins(0, 0, 0, 0)
        self.stamp_btns = {}
        for i, (icon, name) in enumerate(STAMPS):
            b = self._button(icon, name, lambda _c=False, ic=icon: self._set_stamp(ic), checkable=True,
                             color="#93b88d", side=26, icon_side=18)
            srow.addWidget(b, i // 3, i % 3)
            self.stamp_btns[icon] = b
        self.stamp_row = QtWidgets.QWidget()
        self.stamp_row.setLayout(srow)
        col.addWidget(self.stamp_row)
        col.addWidget(self._line())
        acts = QtWidgets.QGridLayout()
        acts.setSpacing(3)
        for i, (icon, tip, slot) in enumerate((
                ("arrow-u-up-left", "Undo  (Ctrl+Z)", lambda: self.o.undo()),
                ("arrow-u-up-right", "Redo  (Ctrl+Shift+Z)", lambda: self.o.undo(True)),
                ("clipboard-text", "Paste an image  (Ctrl+V, or drop a file)", self.o.paste),
                ("push-pin", "Pin to screen  (Ctrl+P)", self.o.pin),
                ("text-aa", "Copy text - OCR  (Ctrl+T)", self.o.ocr),
                ("stack", "Layers  (F7)", self.o.toggle_layers_panel),
                ("grid-four", "Warp the picked marks  (U)", self.o.start_warp),
                ("floppy-disk", "Save  (Ctrl+S) · right click: Save As", self.o.save),
                ("copy", "Copy  (Ctrl+C / Enter)", self.o.copy_and_close),
                ("x", "Close  (Esc)", self.o.close_all))):
            b = self._button(icon, tip, slot, color="#bdbdbd")
            if icon == "floppy-disk":
                b.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda _p: self.o.save(ask=True))
            if icon == "copy":
                b.setIcon(theme.icon(icon, self.ICON, "#1a1a1a"))
                b.setStyleSheet(f"QToolButton {{ background: {theme.ACCENT}; border-radius: 6px; }}")
            acts.addWidget(b, i // 2, i % 2)
        col.addLayout(acts)

    def _set_stamp(self, icon: str) -> None:
        self.o.stamp = icon
        store.data()["stamp"] = icon
        if self.o.selected is not None and self.o.selected.kind == "stamp":
            self.o.push_undo()
            self.o.selected.text = icon
            self.o.touch()
        self.o.update()
        self.sync()

    def _button(self, icon, tip, slot, checkable=False, color="#e0e0e0", side=None, icon_side=None):
        side = side or self.BTN
        icon_side = icon_side or self.ICON
        b = QtWidgets.QToolButton()
        b.setIcon(theme.icon(icon, icon_side, color))
        b.setIconSize(QtCore.QSize(icon_side, icon_side))
        b.setFixedSize(side, side)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        b.clicked.connect(slot)
        return b

    @staticmethod
    def _line():
        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #3d3d3d;")
        return line

    def sync(self) -> None:
        for kind, b in self.tools.items():
            b.setChecked(kind == self.o.tool)
        if getattr(self, "sel_btn", None) is not None:   # the selection button shows its mode
            self.sel_btn.setIcon(theme.icon("selection" if self.o.sel_mode == "rect" else "lasso", self.ICON, self.sel_color))
        self.color_btn.setStyleSheet(f"QToolButton {{ background: {self.o.color.name()}; border: 2px solid #111;"
                                     f" border-radius: 8px; }}")
        self.color2_btn.setStyleSheet(f"QToolButton {{ background: {self.o.color2.name()}; border: 1px solid #1a1a1a;"
                                      f" border-radius: 3px; }}")
        self.size_label.setText(f"{self.o.stroke:.0f} px\nflow {self.o.flow * 100:.0f}%")
        self.text_row.setVisible(self.o.tool in ("text", "callout"))
        self.stamp_row.setVisible(self.o.tool == "stamp")
        for icon, b in self.stamp_btns.items():
            b.setChecked(icon == self.o.stamp)
        self.box_btn.setChecked(self.o.text_box)
        line = self.o.text_outline
        self.outline_btn.setStyleSheet(
            f"QToolButton {{ background: #2b2b2b; border: 3px solid {line}; border-radius: 6px; }}" if line else
            "QToolButton { background: #2b2b2b; border: 1px dashed #6a6a6a; border-radius: 6px; }")
        self.adjustSize()

    def open_picker(self) -> None:
        from .colorpicker import ColorPicker
        if getattr(self.o, "pinned_picker", None) is not None:
            self.o.pinned_picker.raise_()
            return
        picker = ColorPicker(self.o, self.o.color)
        picker.setStyleSheet(theme.STYLE + picker.styleSheet())
        picker.picked.connect(self.o.set_color)
        at = self.color_btn.mapToGlobal(QtCore.QPoint(-picker.sizeHint().width() - 6, 0))
        picker.move(at)
        picker.show()

    def _font_menu(self) -> None:
        menu = QtWidgets.QMenu(self)
        for name in FONTS:
            action = menu.addAction(name)
            f = QtGui.QFont(name)
            action.setFont(f)
            action.setCheckable(True)
            action.setChecked(name == self.o.font_name)
            action.triggered.connect(lambda _c=False, n=name: self._set_font(n))
        menu.exec(self.font_btn.mapToGlobal(QtCore.QPoint(0, self.font_btn.height())))

    def _set_font(self, name: str) -> None:
        self.o.font_name = name
        store.data()["font"] = name
        target = self.o.text_edit.shape if self.o.text_edit else (
            self.o.selected if self.o.selected and self.o.selected.kind == "text" else None)
        if target is not None:
            target.font = name
            if self.o.text_edit:
                self.o._style_text_edit()                        # noqa: SLF001
        self.o.touch()
        self.o.update()

    def _text_target(self):
        return self.o.text_edit.shape if self.o.text_edit else (
            self.o.selected if self.o.selected and self.o.selected.kind == "text" else None)

    def _pick_outline(self) -> None:
        from .colorpicker import ColorPicker
        picker = ColorPicker(self.o, QtGui.QColor(self.o.text_outline or "#000000"))
        picker.setStyleSheet(theme.STYLE + picker.styleSheet())
        picker.picked.connect(lambda c: self._set_outline(c.name()))
        picker.move(self.outline_btn.mapToGlobal(QtCore.QPoint(-picker.sizeHint().width() - 6, 0)))
        picker.show()

    def _set_outline(self, color: str) -> None:
        self.o.text_outline = color
        store.data()["text_outline"] = color
        target = self._text_target()
        if target is not None:
            target.outline = color
        self.sync()
        self.o.touch()
        self.o.update()

    def _toggle_box(self) -> None:
        self.o.text_box = not self.o.text_box
        store.data()["text_box"] = self.o.text_box
        target = self.o.text_edit.shape if self.o.text_edit else (
            self.o.selected if self.o.selected and self.o.selected.kind == "text" else None)
        if target is not None:
            target.box = self.o.text_box
            if self.o.text_edit:
                self.o._style_text_edit()                        # noqa: SLF001
        self.sync()
        self.o.touch()
        self.o.update()


def _icon_tile(p, rect, icon) -> None:
    side = rect.width() * 0.5
    p.drawImage(QtCore.QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side),
                theme.icon_image(icon, 48, "#ffffff"))


class BrushScroll(QtWidgets.QWidget):
    """The brushes in a column at the cursor, Painter's previews and names."""
    ROW = 58

    def __init__(self, overlay, center):
        super().__init__(overlay)
        from . import brushes
        self.o = overlay
        self.ids = brushes.order()
        self.thumbs = {b: QtGui.QPixmap.fromImage(brushes.thumb(b)) for b in self.ids}
        self.names = {b: brushes.name(b) for b in self.ids}
        self.start = overlay.brush
        self.index = self.ids.index(overlay.brush) if overlay.brush in self.ids else 0
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        w, h = 260, self.ROW * len(self.ids) + 12
        x = min(max(4, center.x() - w / 2), overlay.width() - w - 4)
        y = min(max(4, center.y() - h / 2), overlay.height() - h - 4)
        self.setGeometry(int(x), int(y), w, h)
        self.show()
        self.setFocus()

    def paintEvent(self, _e):                                    # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setPen(QtGui.QPen(QtGui.QColor("#1a1a1a"), 1))
        p.setBrush(QtGui.QColor(36, 36, 36, 240))
        p.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        font = QtGui.QFont("Segoe UI")
        font.setPixelSize(13)
        for i, b in enumerate(self.ids):
            r = QtCore.QRectF(6, 6 + i * self.ROW, self.width() - 12, self.ROW - 4)
            if i == self.index:
                p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT), 1.5))
                p.setBrush(QtGui.QColor("#4a3420"))
                p.drawRoundedRect(r, 6, 6)
            thumb = self.thumbs[b]
            box = QtCore.QRectF(r.left() + 6, r.top() + 3, 96, r.height() - 6)
            p.fillRect(box, QtGui.QColor("#1c1c1c"))
            if not thumb.isNull():
                t = thumb.scaled(int(box.width()), int(box.height()), QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                 QtCore.Qt.TransformationMode.SmoothTransformation)
                p.drawPixmap(QtCore.QPointF(box.center().x() - t.width() / 2, box.center().y() - t.height() / 2), t)
            font.setBold(i == self.index)
            p.setFont(font)
            p.setPen(QtGui.QColor("#ffffff" if i == self.index else "#cfcfcf"))
            p.drawText(r.adjusted(112, 0, -6, 0), QtCore.Qt.AlignmentFlag.AlignVCenter, self.names[b])

    def _row_at(self, pos) -> int:
        return max(0, min(len(self.ids) - 1, int((pos.y() - 6) // self.ROW)))

    def wheelEvent(self, e):                                     # noqa: N802
        self.index = (self.index + (-1 if e.angleDelta().y() > 0 else 1)) % len(self.ids)
        self.o.set_brush(self.ids[self.index])            # in hand at once, as the scroll goes
        self.update()

    def mouseMoveEvent(self, e):                                 # noqa: N802
        self.index = self._row_at(e.position())
        self.update()

    def mouseReleaseEvent(self, e):                              # noqa: N802
        self.o.set_brush(self.ids[self._row_at(e.position())])
        self.close()

    def keyPressEvent(self, e):                                  # noqa: N802
        if e.key() == QtCore.Qt.Key.Key_Escape:
            self.o.set_brush(self.start)                  # cancelled: the old brush back
        elif e.key() in (QtCore.Qt.Key.Key_Up, QtCore.Qt.Key.Key_Down):
            self.index = (self.index + (-1 if e.key() == QtCore.Qt.Key.Key_Up else 1)) % len(self.ids)
            self.o.set_brush(self.ids[self.index])
            self.update()
            return
        else:
            self.o.set_brush(self.ids[self.index])
        self.close()

    def closeEvent(self, e):                                     # noqa: N802
        if getattr(self.o, "ring", None) is self:
            self.o.ring = None
        self.o.setFocus()
        super().closeEvent(e)


class Ring(QtWidgets.QWidget):
    """A pie at the cursor: move toward an item and click,
    or let go of the mouse on it; Esc or the same key again closes it."""

    def __init__(self, overlay, center, items, current, on_pick, radius=96, tile=30):
        super().__init__(overlay)
        self.o, self.items, self.current, self.on_pick = overlay, items, current, on_pick
        self.radius, self.tile = radius, tile
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        side = int(radius * 2 + tile * 2 + 40)
        self.setGeometry(int(center.x() - side / 2), int(center.y() - side / 2), side, side)
        self.hover = None
        self.show()
        self.setFocus()

    def _slots(self):
        c = QtCore.QPointF(self.width() / 2, self.height() / 2)
        n = len(self.items)
        for i, item in enumerate(self.items):
            a = -math.pi / 2 + i * 2 * math.pi / n
            yield item, QtCore.QPointF(c.x() + math.cos(a) * self.radius, c.y() + math.sin(a) * self.radius)

    def paintEvent(self, _e):                                    # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        c = QtCore.QPointF(self.width() / 2, self.height() / 2)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(22, 22, 22, 215))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 30), 1))
        p.drawEllipse(c, self.radius + self.tile + 8, self.radius + self.tile + 8)
        for (key, name, draw), pt in self._slots():
            on = key == self.hover
            current = key == self.current
            p.setBrush(QtGui.QColor("#4a4a4a" if on else "#363636"))
            p.setPen(QtGui.QPen(QtGui.QColor(theme.ACCENT if (on or current) else "#5a5a5a"), 2 if on or current else 1))
            p.drawEllipse(pt, self.tile, self.tile)
            p.save()
            draw(p, QtCore.QRectF(pt.x() - self.tile, pt.y() - self.tile, 2 * self.tile, 2 * self.tile))
            p.restore()
        label = next((n for k, n, _d in self.items if k == (self.hover or self.current)), "")
        if label:
            font = QtGui.QFont("Segoe UI")
            font.setPixelSize(13)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QtGui.QColor("#ffffff"))
            p.drawText(QtCore.QRectF(c.x() - 80, c.y() - 12, 160, 24), QtCore.Qt.AlignmentFlag.AlignCenter, label)

    def mouseMoveEvent(self, e):                                 # noqa: N802
        c = QtCore.QPointF(self.width() / 2, self.height() / 2)
        if (e.position() - c).manhattanLength() < self.radius * 0.35:
            self.hover = None
        else:
            best = min(self._slots(), key=lambda sl: (sl[1] - e.position()).manhattanLength())
            self.hover = best[0][0]
        self.update()

    def mouseReleaseEvent(self, e):                              # noqa: N802
        if self.hover:
            key = self.hover
            self.close()
            self.on_pick(key)
        elif e.button() != QtCore.Qt.MouseButton.NoButton:
            self.close()

    def keyPressEvent(self, e):                                  # noqa: N802
        self.close()

    def closeEvent(self, e):                                     # noqa: N802
        if getattr(self.o, "ring", None) is self:
            self.o.ring = None           # at once - the deferred delete comes later
        self.o.setFocus()
        super().closeEvent(e)

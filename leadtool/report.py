"""Reports: screenshots of an asset in one row over a dark template, a black band at the bottom - TASK / ASSET / STAGE on
the left, an optional logo on the right - that always spans the whole width.

TASK / ASSET / STAGE are typed in the bar; the Recent list brings back the
ones of a report saved before."""
import glob
import os
import re

from PySide6 import QtCore, QtGui, QtWidgets

from . import store, theme

BG = QtGui.QColor(36, 36, 36)                 # the template's grey
BAND = 101 / 750                              # band height : picture height (the template: 101 px under 750)
STAGES = ("MP / UV", "TEXTURES", "IN REVIEW")
VALUE = QtGui.QColor(160, 160, 160)
LABEL = VALUE                                 # one colour for "TASK:" and its value


# ------------------------------------------------------------------ the band
_font_family = None


def band_font() -> str:
    """Myriad Pro (the template's) when this PC has it - Photoshop installs it -
    else Segoe UI."""
    global _font_family
    if _font_family is None:
        fams = set(QtGui.QFontDatabase.families())
        _font_family = next((f for f in ("Myriad Pro", "MyriadPro") if f in fams), "")
        if not _font_family:
            pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
            for path in glob.glob(os.path.join(pf, "Adobe", "*", "Required", "Fonts", "MyriadPro-Regular.otf")) + \
                    glob.glob(os.path.join(pf, "Common Files", "Adobe", "Fonts", "MyriadPro-Regular.otf")):
                fid = QtGui.QFontDatabase.addApplicationFont(path)
                got = QtGui.QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                if got:
                    _font_family = got[0]
                    break
        _font_family = _font_family or "Segoe UI"
    return _font_family


_logo = None


def logo() -> QtGui.QImage:
    """Your own logo file (double click the logo place, bottom right of the band); none ships with the app."""
    global _logo
    if _logo is None:
        _logo = QtGui.QImage(os.path.join(store.app_dir(), "report_logo.png"))
    return _logo


def set_logo(path: str) -> bool:
    """A logo file of yours: kept beside the data; a logo on black (no transparency) gets the
    black taken out, so it sits on the band cleanly."""
    global _logo
    image = QtGui.QImage(path)
    if image.isNull():
        return False
    image = image.convertToFormat(QtGui.QImage.Format.Format_ARGB32)
    if not image.hasAlphaChannel() or QtGui.QColor(image.pixel(0, 0)).alpha() == 255:
        import numpy as np
        w, h = image.width(), image.height()
        a = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes()).reshape(h, image.bytesPerLine())[:, :w * 4]
        a = a.reshape(h, w, 4).astype(np.float32)               # B G R A
        cover = a[..., :3].max(axis=2)                           # light on black: brightness = cover
        rgb = np.where(cover[..., None] > 0, a[..., :3] / np.maximum(cover[..., None], 1) * 255, 0)
        out = np.dstack([np.clip(rgb, 0, 255), cover]).astype(np.uint8)
        image = QtGui.QImage(out.data, w, h, w * 4, QtGui.QImage.Format.Format_ARGB32).copy()
    box = _opaque_box(image)
    if box is not None:
        image = image.copy(box)                                  # no empty margins round it
    image.save(os.path.join(store.app_dir(), "report_logo.png"))
    _logo = None
    return True


def _opaque_box(image: QtGui.QImage):
    import numpy as np
    w, h = image.width(), image.height()
    a = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes()).reshape(h, image.bytesPerLine())[:, :w * 4]
    alpha = a.reshape(h, w, 4)[..., 3]
    ys, xs = np.nonzero(alpha > 12)
    if not len(xs):
        return None
    m = 4
    return QtCore.QRect(max(0, xs.min() - m), max(0, ys.min() - m), min(w, xs.max() + m + 1) - max(0, xs.min() - m),
                        min(h, ys.max() + m + 1) - max(0, ys.min() - m))


def logo_rect(region: QtCore.QRectF, band: float) -> QtCore.QRectF:
    lg = logo()
    h = band * 0.61
    w = h * lg.width() / lg.height() if not lg.isNull() else h * 2.5      # no logo yet: its place, to double click
    r = QtCore.QRectF(region.left(), region.bottom() - band, region.width(), band)
    return QtCore.QRectF(r.right() - band * 0.18 - w, r.center().y() - h / 2 - band * 0.01, w, h)


def band_height(picture_height: float) -> float:
    return picture_height * BAND


def paint_band(p: QtGui.QPainter, region: QtCore.QRectF, band: float, task: str, asset: str, stage: str) -> None:
    """The black band across the bottom of region, band px high."""
    r = QtCore.QRectF(region.left(), region.bottom() - band, region.width(), band)
    p.save()
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)
    p.fillRect(r, QtGui.QColor(0, 0, 0))
    font = QtGui.QFont(band_font())
    font.setPixelSize(max(6, round(band * 0.235)))
    font.setCapitalization(QtGui.QFont.Capitalization.AllUppercase)
    p.setFont(font)
    fm = QtGui.QFontMetricsF(font)
    line = band * 0.232
    x = r.left() + band * 0.11
    y0 = r.top() + band * 0.255
    for i, (label, value) in enumerate((("Task", task), ("Asset", asset), ("Stage", stage))):
        base = y0 + i * line
        p.setPen(LABEL)
        p.drawText(QtCore.QPointF(x, base), label)
        w = fm.horizontalAdvance(label.upper())
        p.setPen(VALUE)
        p.drawText(QtCore.QPointF(x + w, base), ": " + value)
    lg = logo()
    if not lg.isNull():
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(logo_rect(region, band), lg)
    p.restore()


class ReportBar(QtWidgets.QWidget):
    """Over the report: TASK / ASSET / STAGE (all editable), the recent ones,
    add a screenshot, the same area again, save, copy."""

    def __init__(self, overlay):
        super().__init__(overlay)
        self.o = overlay
        self.setObjectName("ltReportBar")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.STYLE + "#ltReportBar { background: #262626; border: 1px solid #141414; border-radius: 8px; }"
                           "QLabel { color: #9a9a9a; } QLineEdit, QComboBox { min-height: 24px; }")
        self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        rep = overlay.report
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)
        recent = self._btn("list-bullets", "Recent reports: pick one - its TASK and ASSET come back", lambda: None)
        recent.clicked.connect(lambda _c=False, b=recent: self._recent_menu(b))
        row.addWidget(recent)
        self.task = self._field(row, "Task", rep.get("task", ""), 2)
        self.asset = self._field(row, "Asset", rep.get("asset", ""), 2)
        row.addWidget(QtWidgets.QLabel("Stage"))
        self.stage = QtWidgets.QComboBox()
        self.stage.setEditable(True)
        self.stage.addItems(STAGES)
        self.stage.setCurrentText(rep.get("stage", STAGES[0]))
        self.stage.currentTextChanged.connect(self._changed)
        self.stage.setMinimumWidth(self.stage.fontMetrics().horizontalAdvance(max(STAGES, key=len)) + 40)
        row.addWidget(self.stage, 1)
        row.addSpacing(6)
        bgb = self._btn("palette", "The report's background colour (under the screenshots)", lambda: None)
        bgb.clicked.connect(lambda _c=False, b=bgb: self.o.pick_background(b.mapToGlobal(QtCore.QPoint(0, b.height() + 4))))
        row.addWidget(bgb)
        row.addWidget(self._text_btn("camera", "Screenshot", "Add a screenshot at the end of the row (Ctrl+V adds a copied picture)",
                                     self.o.report_shot, accent=True))
        row.addWidget(self._text_btn("clock-counter-clockwise", "Same area", "The same area again - no selecting",
                                     lambda: self.o.report_shot(True)))
        row.addWidget(self._btn("floppy-disk", "Save PNG (right click: choose the folder)", self.o.report_save))
        row.addWidget(self._btn("copy", "Copy the report", self.o.copy_and_close))
        row.addWidget(self._btn("plus", "New report (this one is dropped)", lambda: self.o.app.open_report(new=True)))
        self.status = QtWidgets.QLabel()
        self.status.setStyleSheet("color: #8a8a8a;")
        row.addWidget(self.status)

    def _btn(self, icon, tip, slot, accent=False):
        b = QtWidgets.QToolButton()
        b.setIcon(theme.icon(icon, 18, "#1a1a1a" if accent else "#d0d0d0"))
        b.setIconSize(QtCore.QSize(18, 18))
        b.setFixedSize(32, 30)
        b.setToolTip(tip)
        b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        if accent:
            b.setStyleSheet(f"QToolButton {{ background: {theme.ACCENT}; border-radius: 6px; }}")
        if icon == "floppy-disk":
            b.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _p: self.o.report_save(ask=True))
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _text_btn(self, icon, text, tip, slot, accent=False):
        b = QtWidgets.QPushButton(theme.icon(icon, 16, "#1a1a1a" if accent else "#d0d0d0"), " " + text)
        b.setToolTip(tip)
        b.setFixedHeight(30)
        b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        if accent:
            b.setStyleSheet(f"QPushButton {{ background: {theme.ACCENT}; color: #1a1a1a; font-weight: bold;"
                            f" padding: 0 12px; border-radius: 6px; }}")
        else:
            b.setStyleSheet("QPushButton { padding: 0 10px; }")
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _field(self, row, label, text, stretch):
        row.addWidget(QtWidgets.QLabel(label))
        e = QtWidgets.QLineEdit(text)
        e.textChanged.connect(self._changed)
        row.addWidget(e, stretch)
        return e

    def _changed(self, _t=None) -> None:
        rep = self.o.report
        rep.update(task=self.task.text().strip(), asset=self.asset.text().strip(),
                   stage=self.stage.currentText().strip())
        self.o.update()

    def _recent_menu(self, button) -> None:
        """The reports saved before, by mesh name (newest first): one click fills TASK and ASSET;
        the stage stays as chosen (the same asset goes MP/UV -> TEXTURES -> IN REVIEW)."""
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(theme.STYLE)
        menu.setToolTipsVisible(True)
        presets = store.get("report_presets") or []
        for pr in presets:
            a = menu.addAction(pr.get("asset") or pr.get("task") or "?")
            a.setToolTip(pr.get("task", ""))
            a.triggered.connect(lambda _c=False, x=pr: self.use_preset(x))
        if not presets:
            none = menu.addAction("Nothing saved yet - Save remembers TASK and ASSET")
            none.setEnabled(False)
        else:
            menu.addSeparator()
            menu.addAction("Clear the list", lambda: store.put("report_presets", []))
        menu.exec(button.mapToGlobal(QtCore.QPoint(0, button.height() + 4)))

    def use_preset(self, pr) -> None:
        self.task.setText(pr.get("task", ""))
        self.asset.setText(pr.get("asset", ""))
        self._changed()


def remember_preset(task: str, asset: str) -> None:
    """Saved reports are remembered by mesh (asset) name - newest first, 40 at most."""
    if not (task or asset):
        return
    import time
    rest = [p for p in store.get("report_presets") or [] if (p.get("asset"), p.get("task")) != (asset, task)
            and not (asset and p.get("asset") == asset)]
    store.put("report_presets", [{"asset": asset, "task": task, "time": time.strftime("%Y-%m-%d")}] + rest[:39])


class ShotPill(QtWidgets.QWidget):
    """While the report steps aside: set up the view, then Shot. A small bar at
    the top of the screen, always on top."""

    def __init__(self, app, report_overlay):
        super().__init__(None, QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.WindowStaysOnTopHint
                         | QtCore.Qt.WindowType.Tool)
        self.app, self.rep = app, report_overlay
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setObjectName("ltPill")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.STYLE + "#ltPill { background: #262626; border: 1px solid #141414; border-radius: 10px; }"
                           "QLabel { color: #bdbdbd; }")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        row.addWidget(QtWidgets.QLabel("Set up the view, then"))
        for text, slot, accent in (("Shot", self._shot, True), ("Same area", lambda: self._shot(True), False),
                                   ("Back to report", self._back, False)):
            b = QtWidgets.QPushButton(text)
            b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            if accent:
                b.setStyleSheet(f"QPushButton {{ background: {theme.ACCENT}; color: #1a1a1a; font-weight: bold;"
                                f" padding: 4px 14px; border-radius: 6px; }}")
            b.clicked.connect(lambda _c=False, f=slot: f())
            row.addWidget(b)
        self.adjustSize()
        g = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or QtGui.QGuiApplication.primaryScreen()
        a = g.availableGeometry()
        self.move(a.center().x() - self.width() // 2, a.top() + 12)
        self.show()

    def _shot(self, same: bool = False) -> None:
        self.close()
        QtCore.QTimer.singleShot(150, lambda: self.app.capture_for(self.rep._report_add, repeat=same))

    def _back(self) -> None:
        self.close()
        self.rep._report_add(None)

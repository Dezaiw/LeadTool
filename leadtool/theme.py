"""The look: Painter-dark greys, one blue accent, Phosphor duotone icons."""
import os
import sys

from PySide6 import QtCore, QtGui, QtSvg

ACCENT = "#f28c28"
BG = "#333333"
BG_DARK = "#262626"
BORDER = "#4a4a4a"
TEXT = "#d8d8d8"
HINT = "#8a8a8a"

STYLE = f"""
QWidget {{ color: {TEXT}; font-family: "Segoe UI"; font-size: 12px; }}
QWidget#ltPanel, QWidget#ltLauncher, QWidget#ltNote, QWidget#ltPicker, QDialog {{ background: {BG}; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 3px; }}
QToolButton:hover {{ background: #3d3d3d; border-color: {BORDER}; }}
QToolButton:checked {{ background: #4a3420; border-color: {ACCENT}; }}
QPushButton {{ background: #3a3a3a; border: 1px solid {BORDER}; border-radius: 3px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: #6e6e6e; }}
QPushButton[role="primary"] {{ background: {ACCENT}; border-color: {ACCENT}; color: #1a1a1a; font-weight: bold; }}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{ background: {BG_DARK}; border: 1px solid #1f1f1f;
    border-radius: 3px; padding: 4px 6px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QListWidget {{ background: {BG_DARK}; border: 1px solid #1f1f1f; border-radius: 3px; outline: 0; }}
QListWidget::item {{ padding: 5px 6px; border-radius: 2px; }}
QListWidget::item:hover {{ background: #383838; }}
QListWidget::item:selected {{ background: #4a3420; color: #fff; }}
QLabel[role="hint"] {{ color: {HINT}; }}
QLabel[role="section"] {{ color: #e8e8e8; font-weight: bold; font-size: 11px; letter-spacing: 1px; }}
QTabBar::tab {{ background: #2b2b2b; color: #9a9a9a; padding: 6px 7px; border: none; }}
QTabBar::tab:selected {{ background: {BG}; color: #fff; border-bottom: 2px solid {ACCENT}; }}
QTabWidget::pane {{ border: none; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid #5a5a5a; border-radius: 2px; background: {BG_DARK}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QMenu {{ background: #2b2b2b; border: 1px solid #1f1f1f; padding: 4px; }}
QMenu::item {{ padding: 5px 22px 5px 10px; border-radius: 2px; }}
QMenu::item:selected {{ background: #4a3420; }}
QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: #4a4a4a; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: #1f1f1f; color: #e8e8e8; border: 1px solid #444; padding: 4px; }}
"""

_cache = {}


def _icons_dir() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "icons")
    return path if os.path.isdir(path) else os.path.join(base, "leadtool", "icons")


def icon_image(name: str, px: int, color: str = "#e0e0e0") -> QtGui.QImage:
    key = (name, px, color)
    if key in _cache:
        return _cache[key]
    image = QtGui.QImage(px, px, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    try:
        with open(os.path.join(_icons_dir(), name + ".svg"), "rb") as handle:
            data = handle.read().replace(b'opacity="0.2"', b'opacity="0.38"')
        renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(data))
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QtCore.QRectF(0, 0, px, px))
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
        # filled and soft: lighter at the top, deeper at the bottom
        base = QtGui.QColor(color)
        grad = QtGui.QLinearGradient(0, 0, 0, px)
        grad.setColorAt(0, base.lighter(118))
        grad.setColorAt(1, base.darker(112))
        painter.fillRect(image.rect(), grad)
        painter.end()
    except OSError:
        pass
    _cache[key] = image
    return image


def icon(name: str, size: int = 18, color: str = "#e0e0e0", dpr: float = 2.0) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap.fromImage(icon_image(name, int(size * dpr), color))
    pixmap.setDevicePixelRatio(dpr)
    result = QtGui.QIcon(pixmap)
    checked = QtGui.QPixmap.fromImage(icon_image(name, int(size * dpr), "#ffffff"))
    checked.setDevicePixelRatio(dpr)
    result.addPixmap(checked, QtGui.QIcon.Mode.Normal, QtGui.QIcon.State.On)
    return result


def app_icon() -> QtGui.QIcon:
    """A blue tile with the crop glyph - the tray and the windows."""
    out = QtGui.QIcon()
    for side in (16, 24, 32, 48, 64, 256):
        pixmap = QtGui.QPixmap(side, side)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pixmap)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        grad = QtGui.QLinearGradient(0, 0, 0, side)
        grad.setColorAt(0, QtGui.QColor("#ffa64d"))
        grad.setColorAt(1, QtGui.QColor("#d9650f"))
        p.setBrush(grad)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.drawRoundedRect(QtCore.QRectF(0, 0, side, side), side * 0.22, side * 0.22)
        glyph = icon_image("crop", int(side * 0.7), "#ffffff")
        p.drawImage(QtCore.QRectF(side * 0.15, side * 0.15, side * 0.7, side * 0.7), glyph)
        p.end()
        out.addPixmap(pixmap)
    return out


FOLDER = "#d9b26f"          # the default folder: warm beige


def folder_pixmap(side: int, color: str = "", emblem: str = "", dpr: float = 2.0) -> QtGui.QPixmap:
    """A filled folder with a soft gradient - tinted by the item's colour
    label - and an optional small glyph on its front."""
    px = int(side * dpr)
    pixmap = QtGui.QPixmap(px, px)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    base = QtGui.QColor(color or FOLDER)
    u = px / 16.0
    back = QtGui.QPainterPath()
    back.addRoundedRect(QtCore.QRectF(1 * u, 2.5 * u, 6.5 * u, 3 * u), 1.0 * u, 1.0 * u)
    back.addRoundedRect(QtCore.QRectF(1 * u, 3.6 * u, 14 * u, 10.4 * u), 1.4 * u, 1.4 * u)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(base.darker(135))
    p.drawPath(back.simplified())
    front = QtCore.QRectF(1 * u, 5.2 * u, 14 * u, 8.8 * u)
    grad = QtGui.QLinearGradient(front.topLeft(), front.bottomRight())
    grad.setColorAt(0, base.lighter(118))
    grad.setColorAt(1, base.darker(108))
    p.setBrush(grad)
    p.drawRoundedRect(front, 1.4 * u, 1.4 * u)
    if emblem:
        glyph = icon_image(emblem, int(px * 0.42), base.darker(190).name())
        p.drawImage(QtCore.QRectF(px * 0.3, px * 0.4, px * 0.42, px * 0.42), glyph)
    p.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap

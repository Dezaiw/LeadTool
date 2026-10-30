"""The whole desktop frozen into one picture, every monitor in place."""
from PySide6 import QtCore, QtGui


def virtual_geometry() -> QtCore.QRect:
    rect = QtCore.QRect()
    for screen in QtGui.QGuiApplication.screens():
        rect = rect.united(screen.geometry())
    return rect


def grab_desktop():
    """(pixmap of the virtual desktop at the primary screen's pixel ratio,
    its logical geometry)."""
    geo = virtual_geometry()
    dpr = QtGui.QGuiApplication.primaryScreen().devicePixelRatio()
    canvas = QtGui.QPixmap(int(geo.width() * dpr), int(geo.height() * dpr))
    canvas.fill(QtCore.Qt.GlobalColor.black)
    painter = QtGui.QPainter(canvas)
    painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
    for screen in QtGui.QGuiApplication.screens():
        shot = screen.grabWindow(0)
        g = screen.geometry().translated(-geo.topLeft())
        target = QtCore.QRectF(g.x() * dpr, g.y() * dpr, g.width() * dpr, g.height() * dpr)
        painter.drawPixmap(target, shot, QtCore.QRectF(shot.rect()))
    painter.end()
    canvas.setDevicePixelRatio(dpr)
    return canvas, geo


def screen_at_cursor() -> QtGui.QScreen:
    return QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or QtGui.QGuiApplication.primaryScreen()


def grab_screen(screen: QtGui.QScreen = None):
    """ONE monitor - the one under the cursor (the other stays
    live, to drag a picture in from it or copy one for Ctrl+V)."""
    screen = screen or screen_at_cursor()
    shot = screen.grabWindow(0)
    shot.setDevicePixelRatio(screen.devicePixelRatio())
    return shot, screen.geometry()

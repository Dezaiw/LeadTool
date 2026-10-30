"""The brush engine, with Substance Painter's own brushes (
Wet Soft Round, Calligraphic, Basic Soft, Wet Hard, Marker, Pencil).

Each brush = Painter's alpha (rendered from the preset's own .sbsar with the
preset's values) + the preset's spacing / flow / jitters / follow-path, read
from Painter's tool panel (brushes/brushes.json). Stamps along the stroke:
FLOW per stamp (paint builds up inside one stroke), stroke OPACITY applied
once when it is shown, ANGLE turns the tip (Ctrl + drag up / down, as in
Painter). Fast because nothing is redrawn: each mouse move stamps only the
new part into the stroke's own picture.
"""
import json
import math
import os
import random
import sys

from PySide6 import QtCore, QtGui

_defs = None
_tips = {}
_masks = {}


def _folder() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "brushes")
    return path if os.path.isdir(path) else os.path.join(base, "leadtool", "brushes")


def defs() -> dict:
    global _defs
    if _defs is None:
        with open(os.path.join(_folder(), "brushes.json"), encoding="utf-8") as handle:
            _defs = {d["id"]: d for d in json.load(handle)}
    return _defs


def order() -> list:
    return list(defs())


def spec(brush: str) -> dict:
    return defs().get(brush) or next(iter(defs().values()))


def name(brush: str) -> str:
    return spec(brush)["name"]


def thumb(brush: str) -> QtGui.QImage:
    return QtGui.QImage(os.path.join(_folder(), spec(brush)["id"] + "_thumb.png"))


def _mask(brush: str) -> QtGui.QImage:
    """Painter's alpha as a white stamp whose transparency is the alpha."""
    bid = spec(brush)["id"]
    if bid not in _masks:
        grey = QtGui.QImage(os.path.join(_folder(), bid + ".png")).convertToFormat(QtGui.QImage.Format.Format_Grayscale8)
        white = QtGui.QImage(grey.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        white.fill(QtGui.QColor(255, 255, 255))
        white.setAlphaChannel(grey)
        _masks[bid] = white
    return _masks[bid]


def tip(brush: str, size: float) -> QtGui.QImage:
    side = max(2, int(round(size)))
    key = (spec(brush)["id"], side)
    if key not in _tips:
        if len(_tips) > 200:
            _tips.clear()
        _tips[key] = _mask(brush).scaled(side, side, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                         QtCore.Qt.TransformationMode.SmoothTransformation)
    return _tips[key]


def stamp_size(width: float) -> float:
    return min(max(1.0, width * 2.0), 640.0)               # the stamp spans the stroke's width


class StrokeRenderer:
    """Stamps one stroke into its own transparent picture, incrementally."""

    def __init__(self, shape, base: QtGui.QImage = None):
        self.s = shape
        self.rnd = random.Random(shape.seed)
        self.image = None                   # QImage, grown as the stroke grows
        self.origin = QtCore.QPointF()      # where image (0, 0) is, in canvas pixels
        self.done = 0                       # points already stamped
        self.carry = 0.0                    # distance since the last stamp

    def _ensure(self, rect: QtCore.QRectF) -> None:
        rect = rect.adjusted(-2, -2, 2, 2)
        if self.image is None:
            target = rect.adjusted(-64, -64, 64, 64).toAlignedRect()
            self.image = QtGui.QImage(target.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            self.image.fill(QtCore.Qt.GlobalColor.transparent)
            self.origin = QtCore.QPointF(target.topLeft())
            return
        have = QtCore.QRectF(self.origin, QtCore.QSizeF(self.image.size()))
        if have.contains(rect):
            return
        target = have.united(rect.adjusted(-96, -96, 96, 96)).toAlignedRect()
        grown = QtGui.QImage(target.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        grown.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(grown)
        p.drawImage(self.origin - QtCore.QPointF(target.topLeft()), self.image)
        p.end()
        self.image, self.origin = grown, QtCore.QPointF(target.topLeft())

    def extend(self) -> None:
        """Stamp the points added since the last call."""
        s = self.s
        pts = s.points
        if not pts:
            return
        sp = spec(s.brush)
        size = stamp_size(s.width)
        step = max(0.5, size * sp["spacing"])
        start = max(0, self.done - 1)
        if self.done == 0:
            self._stamp(pts[0], size, 0.0, sp)
        for a, b in zip(pts[start:], pts[start + 1:]):
            seg = math.hypot(b.x() - a.x(), b.y() - a.y())
            if seg <= 0:
                continue
            angle = math.atan2(b.y() - a.y(), b.x() - a.x())
            t = step - self.carry
            while t <= seg:
                pt = QtCore.QPointF(a.x() + (b.x() - a.x()) * t / seg, a.y() + (b.y() - a.y()) * t / seg)
                self._stamp(pt, size, angle, sp)
                t += step
            self.carry = seg - (t - step)
        self.done = len(pts)

    def _stamp(self, pt, size, angle, sp) -> None:
        s = self.s
        rnd = self.rnd
        d = size * (1 - rnd.random() * sp["size_jitter"])
        if sp["position_jitter"]:
            pt = QtCore.QPointF(pt.x() + rnd.gauss(0, 0.5) * size * sp["position_jitter"],
                                pt.y() + rnd.gauss(0, 0.5) * size * sp["position_jitter"])
        rotation = s.angle + (math.degrees(angle) + 90 if sp["follow_path"] else 0.0)
        if sp["angle_jitter"]:
            rotation += rnd.uniform(-1, 1) * sp["angle_jitter"]
        flow = s.flow * (1 - rnd.random() * sp["flow_jitter"])     # the flow IS the brush's (set from the preset)
        stamp = tip(s.brush, d)
        self._ensure(QtCore.QRectF(pt.x() - d, pt.y() - d, 2 * d, 2 * d))
        colored = QtGui.QImage(stamp.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        colored.fill(s.color)
        cp = QtGui.QPainter(colored)
        cp.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_DestinationIn)
        cp.drawImage(0, 0, stamp)
        cp.end()
        p = QtGui.QPainter(self.image)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(pt - self.origin)
        if rotation:
            p.rotate(rotation)
        p.setOpacity(max(0.0, min(1.0, flow)))
        p.drawImage(QtCore.QPointF(-colored.width() / 2, -colored.height() / 2), colored)
        p.end()

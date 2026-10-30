"""What gets drawn on a capture. Every mark stays an OBJECT (select, move,
recolour, delete) until the picture is copied / saved - never burnt in
pixels while you work.

Coordinates are the overlay's logical pixels."""
import base64
import copy
import math
import random

from PySide6 import QtCore, QtGui

KINDS = ("stroke", "line", "arrow", "rect", "ellipse", "text", "callout", "counter", "stamp", "blur", "pixelate",
         "spotlight", "magnify", "image", "poly")
#: the stamps (Snagit's): quick verdicts on a picture - icon, name
STAMPS = (("check-circle", "Good"), ("x-circle", "Wrong"), ("warning-circle", "Fix this"), ("question", "Why?"),
          ("star", "Love it"), ("heart", "Nice"), ("thumbs-up", "Yes"), ("thumbs-down", "No"),
          ("fire", "Hot"), ("lightbulb", "Idea"))
#: the brushes of the stroke tool (Q): id, name - Paint's set without the odd ones
from . import brushes as _engine                      # noqa: E402
BRUSHES = tuple((b, _engine.name(b)) for b in _engine.order())
_STROKES = ("stroke", "line", "arrow")


class Shape:
    def __init__(self, kind: str, color="#ff3b30", width=4.0, opacity=1.0):
        self.kind = kind
        self.color = QtGui.QColor(color)
        self.width = float(width)
        self.opacity = float(opacity)
        self.points = []                  # QPointF list (pen / marker / line / arrow: 2 points)
        self.rect = QtCore.QRectF()       # rect / ellipse / blur / image / text box
        self.text = ""
        self.font = "Segoe UI"
        self.box = False                  # text on a dark plate
        self.outline = "#000000"          # text outline colour, "" = none
        self.number = 1
        self.brush = "pen"
        self.flow = 1.0
        self.angle = 0.0                          # the tip turned (Ctrl + drag up / down)
        self.erase = False                        # an eraser stroke: the brush, inverted
        self._render = None                       # the stroke's own stamped picture (brushes.py)
        self.seed = random.randrange(1 << 30)     # the grain of a textured brush stays put
        self.image = None                 # QPixmap for "image"
        self.xform = QtGui.QTransform()   # turned / scaled with the W frame (never edited in place)
        self.layer = ""                   # its layer id ("" = the first layer of marks)
        self.warp = None                  # image: 16 control points (0..1 of its rect), a 4x4 bezier mesh
        self.raster = False               # image made from marks (warp): no frame round it
        self.cuts = []                    # eraser strokes that cut THIS mark: they travel with it
        self.shot = False                 # a report's screenshot (laid out in the row)

    # -- geometry ----------------------------------------------------------
    def bounds(self) -> QtCore.QRectF:
        b = self._bounds()
        return b if self.xform.isIdentity() else self.xform.mapRect(b)

    def hit(self, pos: QtCore.QPointF) -> bool:
        if not self.xform.isIdentity():
            pos = self.xform.inverted()[0].map(pos)
        return self._hit(pos)

    def _bounds(self) -> QtCore.QRectF:
        if self.kind in _STROKES:
            if not self.points:
                return QtCore.QRectF()
            xs = [p.x() for p in self.points]
            ys = [p.y() for p in self.points]
            pad = self.width * (3 if self.kind in ("arrow", "stroke") else 1) + 4
            return QtCore.QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).adjusted(-pad, -pad, pad, pad)
        if self.kind == "counter":
            r = self.radius()
            c = self.points[0] if self.points else QtCore.QPointF()
            dot = QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            return dot.united(self.text_rect()) if self.text else dot
        if self.kind in ("text", "callout"):
            r = self.text_rect()
            if self.kind == "callout" and self.points:
                r = r.united(QtCore.QRectF(self.points[0], QtCore.QSizeF(1, 1)))
            return r
        if self.kind == "stamp":
            r = self.radius() * 1.15
            c = self.points[0] if self.points else QtCore.QPointF()
            return QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        if self.kind == "magnify":
            return self.rect.normalized().united(self._lens())
        if self.kind == "poly":                          # a lasso fill
            return QtGui.QPolygonF(self.points).boundingRect()
        if self.kind == "image" and self.warp:
            return QtGui.QPolygonF([pt for row in self.warp_grid(6) for pt in row]).boundingRect()
        return self.rect.normalized()

    # -- warp: a 4x4 bezier patch over the picture ------------------------------
    @staticmethod
    def identity_warp() -> list:
        return [(i / 3, j / 3) for j in range(4) for i in range(4)]

    def warp_at(self, u: float, v: float, warp=None) -> QtCore.QPointF:
        c = warp or self.warp
        bu = ((1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3)
        bv = ((1 - v) ** 3, 3 * v * (1 - v) ** 2, 3 * v * v * (1 - v), v ** 3)
        x = y = 0.0
        for j in range(4):
            for i in range(4):
                w = bu[i] * bv[j]
                x += w * c[j * 4 + i][0]
                y += w * c[j * 4 + i][1]
        r = self.rect.normalized()
        return QtCore.QPointF(r.x() + x * r.width(), r.y() + y * r.height())

    def warp_grid(self, n: int) -> list:
        return [[self.warp_at(i / n, j / n) for i in range(n + 1)] for j in range(n + 1)]

    def radius(self) -> float:
        return 11 + self.width * 1.6

    def _hit(self, pos: QtCore.QPointF) -> bool:
        if self.erase:
            return False
        if self.kind == "poly":
            return QtGui.QPolygonF(self.points).containsPoint(pos, QtCore.Qt.FillRule.OddEvenFill)                          # an eraser stroke is not a thing to pick
        if self.kind in _STROKES:
            tolerance = max(6.0, self.width * 1.2)
            for a, b in zip(self.points, self.points[1:]):
                if _dist_to_segment(pos, a, b) <= tolerance:
                    return True
            return len(self.points) == 1 and _dist(pos, self.points[0]) <= tolerance
        if self.kind == "spotlight":                       # only its edge picks it - the inside is the picture
            r = self.rect.normalized()
            return r.adjusted(-8, -8, 8, 8).contains(pos) and not r.adjusted(8, 8, -8, -8).contains(pos)
        if self.kind == "magnify":
            lens = self._lens()
            c = lens.center()
            return math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= lens.width() / 2 or \
                self.rect.normalized().adjusted(-6, -6, 6, 6).contains(pos)
        if self.kind in ("rect", "ellipse") :
            r = self.rect.normalized()
            outer = r.adjusted(-6, -6, 6, 6)
            inner = r.adjusted(6 + self.width, 6 + self.width, -6 - self.width, -6 - self.width)
            return outer.contains(pos) and not (inner.isValid() and inner.contains(pos))
        return self._bounds().contains(pos)

    def clone(self) -> "Shape":
        """A copy for undo that keeps the stamped picture (shared, never
        re-stamped): Ctrl+Z on brush strokes used to stamp every stroke again."""
        twin = copy.copy(self)
        twin.points = list(self.points)
        twin.rect = QtCore.QRectF(self.rect)
        twin.cuts = [c.clone() for c in self.cuts]
        return twin

    def move(self, dx: float, dy: float) -> None:
        if not self.xform.isIdentity():            # turned / scaled: the move goes on top of that
            self.xform = self.xform * QtGui.QTransform.fromTranslate(dx, dy)
            return
        self.points = [QtCore.QPointF(p.x() + dx, p.y() + dy) for p in self.points]
        self.rect.translate(dx, dy)
        for c in self.cuts:                       # what was erased of it goes along
            c.move(dx, dy)
        if self._render is not None:              # the picture just moves, nothing restamped
            moved = copy.copy(self._render)       # own copy: an undo snapshot shares the old one
            moved.origin = QtCore.QPointF(self._render.origin) + QtCore.QPointF(dx, dy)
            self._render = moved

    def restyle(self) -> None:
        """Colour / size changed: stamp the stroke again (once)."""
        self._render = None

    # -- text ---------------------------------------------------------------
    def qfont(self) -> QtGui.QFont:
        font = QtGui.QFont(self.font)
        font.setPixelSize(int(10 + self.width * 2.5))
        font.setBold(True)
        return font

    def pad(self) -> float:
        return 12.0 if self.kind == "callout" else (6.0 if self.box else 2.0)

    def text_rect(self) -> QtCore.QRectF:
        metrics = QtGui.QFontMetricsF(self.qfont())
        lines = (self.text or " ").split("\n")
        w = max(metrics.horizontalAdvance(line) for line in lines)
        h = metrics.lineSpacing() * len(lines)
        if self.kind == "callout":                         # the bubble sits at the second point
            origin = self.points[1] if len(self.points) > 1 else QtCore.QPointF()
            w = max(w, metrics.horizontalAdvance("Comment"))
        elif self.kind == "counter":                       # the note sits right of the number
            c = self.points[0] if self.points else QtCore.QPointF()
            origin = QtCore.QPointF(c.x() + self.radius() + 8, c.y() - metrics.lineSpacing() / 2 - 2)
        else:
            origin = self.points[0] if self.points else QtCore.QPointF()
        pad = self.pad()
        return QtCore.QRectF(origin.x() - pad, origin.y() - pad, w + 2 * pad, h + 2 * pad)

    # -- drawing -----------------------------------------------------------
    def paint(self, p: QtGui.QPainter, base: QtGui.QPixmap = None) -> None:
        if self.cuts:
            self._paint_cut(p, base)
            return
        self._paint_plain(p, base)

    def _paint_cut(self, p, base) -> None:
        """A mark with eraser strokes on it: drawn on its own little layer,
        the cuts taken out there - so they move / turn / warp with the mark."""
        dev = p.device()
        dpr = dev.devicePixelRatioF() if dev is not None else 1.0
        b = self._bounds().adjusted(-4, -4, 4, 4)
        image = QtGui.QImage(max(1, math.ceil(b.width() * dpr)), max(1, math.ceil(b.height() * dpr)),
                             QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        image.setDevicePixelRatio(dpr)
        q = QtGui.QPainter(image)
        q.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        q.translate(-b.topLeft())
        keep, self.xform = self.xform, QtGui.QTransform()
        try:
            self._paint_plain(q, base)
        finally:
            self.xform = keep
        for c in self.cuts:
            c.paint(q, base)
        q.end()
        p.save()
        if not self.xform.isIdentity():
            p.setTransform(self.xform, True)
        p.drawImage(b.topLeft(), image)
        p.restore()

    def _paint_plain(self, p, base) -> None:
        p.save()
        if not self.xform.isIdentity():
            p.setTransform(self.xform, True)
        p.setOpacity(self.opacity)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        color = QtGui.QColor(self.color)
        getattr(self, "_paint_" + self.kind)(p, color, base)
        p.restore()

    def _pen(self, color, width=None, cap=QtCore.Qt.PenCapStyle.RoundCap):
        return QtGui.QPen(color, width or self.width, QtCore.Qt.PenStyle.SolidLine, cap,
                          QtCore.Qt.PenJoinStyle.RoundJoin)

    def _paint_stroke(self, p, color, base):
        r = self._render
        if r is None or (r.s is not self and r.done < len(self.points)):   # a clone that grew stamps its own
            r = self._render = _engine.StrokeRenderer(self)
        if r.done < len(self.points):
            r.extend()                           # only the new part of the stroke
        if r.image is not None:
            k = _engine.spec(self.brush)["opacity"]
            if self.erase:                        # cut the marks under it - the same brush, inverted
                p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_DestinationOut)
                k = 1.0
            p.setOpacity(self.opacity * k)
            p.drawImage(r.origin, r.image)

    def _paint_line(self, p, color, _base):
        if len(self.points) >= 2:
            p.setPen(self._pen(color))
            p.drawLine(self.points[0], self.points[-1])

    def _paint_arrow(self, p, color, _base):
        """A tapered body and a solid head that grows with the width - reads
        at a glance, the way Snagit / Shottr arrows do."""
        if len(self.points) < 2:
            return
        a, b = self.points[0], self.points[-1]
        length = _dist(a, b)
        if length < 2:
            return
        ux, uy = (b.x() - a.x()) / length, (b.y() - a.y()) / length
        nx, ny = -uy, ux
        head_len = min(length * 0.6, 10 + self.width * 3.2)
        head_w = head_len * 0.62
        neck = QtCore.QPointF(b.x() - ux * head_len * 0.85, b.y() - uy * head_len * 0.85)
        tail_w, neck_w = self.width * 0.35, self.width * 0.75
        poly = QtGui.QPolygonF([
            QtCore.QPointF(a.x() + nx * tail_w, a.y() + ny * tail_w),
            QtCore.QPointF(neck.x() + nx * neck_w, neck.y() + ny * neck_w),
            QtCore.QPointF(b.x() - ux * head_len + nx * head_w, b.y() - uy * head_len + ny * head_w),
            b,
            QtCore.QPointF(b.x() - ux * head_len - nx * head_w, b.y() - uy * head_len - ny * head_w),
            QtCore.QPointF(neck.x() - nx * neck_w, neck.y() - ny * neck_w),
            QtCore.QPointF(a.x() - nx * tail_w, a.y() - ny * tail_w)])
        p.setPen(QtGui.QPen(color, 1, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap,
                            QtCore.Qt.PenJoinStyle.RoundJoin))
        p.setBrush(color)
        p.drawPolygon(poly)

    def _paint_rect(self, p, color, _base):
        p.setPen(self._pen(color, cap=QtCore.Qt.PenCapStyle.SquareCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(self.rect.normalized(), 2, 2)

    def _paint_ellipse(self, p, color, _base):
        p.setPen(self._pen(color))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(self.rect.normalized())

    def _paint_text(self, p, color, _base):
        rect = self.text_rect()
        if self.box:
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(20, 20, 20, 200))
            p.drawRoundedRect(rect, 4, 4)
        p.setFont(self.qfont())
        inner = rect.adjusted(6 if self.box else 2, 6 if self.box else 2, 0, 0)
        if not self.box and self.outline:      # an outline in its own colour keeps it readable anywhere
            halo = QtGui.QPainterPath()
            metrics = QtGui.QFontMetricsF(self.qfont())
            for i, line in enumerate(self.text.split("\n")):
                halo.addText(inner.x(), inner.y() + metrics.ascent() + i * metrics.lineSpacing(), self.qfont(), line)
            p.setPen(QtGui.QPen(QtGui.QColor(self.outline), max(2.0, self.width * 0.7),
                                QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap,
                                QtCore.Qt.PenJoinStyle.RoundJoin))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawPath(halo)
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPath(halo)
            return
        if not self.box:
            p.setPen(color)
            p.setFont(self.qfont())
            p.drawText(inner, QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop, self.text)
            return
        p.setPen(color)
        p.drawText(inner, QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop, self.text)

    def _paint_callout(self, p, color, _base):
        """A speech bubble pointing at the spot (Snagit's callout): the
        colour fills it, the text takes the contrasting black / white."""
        bubble = self.text_rect()
        tip = self.points[0]
        c = bubble.center()
        # the tail leaves the bubble on the side facing the tip
        dx, dy = tip.x() - c.x(), tip.y() - c.y()
        base_w = min(26.0, max(12.0, min(bubble.width(), bubble.height()) * 0.35))
        if abs(dx) * bubble.height() > abs(dy) * bubble.width():
            x = bubble.right() - 6 if dx > 0 else bubble.left() + 6
            a, b = QtCore.QPointF(x, c.y() - base_w / 2), QtCore.QPointF(x, c.y() + base_w / 2)
        else:
            y = bubble.bottom() - 6 if dy > 0 else bubble.top() + 6
            a, b = QtCore.QPointF(c.x() - base_w / 2, y), QtCore.QPointF(c.x() + base_w / 2, y)
        path = QtGui.QPainterPath()
        path.addRoundedRect(bubble, 10, 10)
        tail = QtGui.QPainterPath()
        tail.addPolygon(QtGui.QPolygonF([a, tip, b, a]))
        shape = path.united(tail)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 120), 1.5))
        p.setBrush(color)
        p.drawPath(shape)
        p.setFont(self.qfont())
        p.setPen(QtGui.QColor("#111111" if color.lightnessF() > 0.62 else "#ffffff"))
        pad = self.pad()
        p.drawText(bubble.adjusted(pad, pad - 1, -pad, -pad), QtCore.Qt.AlignmentFlag.AlignLeft
                   | QtCore.Qt.AlignmentFlag.AlignTop, self.text)

    def _paint_stamp(self, p, color, _base):
        """A verdict on the picture: a coloured disc, a white symbol."""
        r = self.radius()
        c = self.points[0]
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 235), max(1.5, r * 0.08)))
        p.setBrush(color)
        p.drawEllipse(c, r, r)
        from . import theme
        side = r * 1.25
        glyph = theme.icon_image(self.text or "check-circle", int(side * 2), "#ffffff")
        p.drawImage(QtCore.QRectF(c.x() - side / 2, c.y() - side / 2, side, side), glyph)

    def _paint_spotlight(self, p, _color, _base):
        """Everything darker but this: where to look."""
        r = self.rect.normalized()
        dark = QtGui.QPainterPath()
        dark.addRect(QtCore.QRectF(-20000, -20000, 40000, 40000))
        hole = QtGui.QPainterPath()
        hole.addRoundedRect(r, 6, 6)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, int(150 * self.opacity)))
        p.setOpacity(1.0)
        p.drawPath(dark.subtracted(hole))

    def _lens(self) -> QtCore.QRectF:
        r = self.rect.normalized()
        radius = max(24.0, max(r.width(), r.height()))         # 2x the picked area
        c = self.points[0] if self.points else QtCore.QPointF(r.right() + radius * 1.3, r.center().y())
        return QtCore.QRectF(c.x() - radius, c.y() - radius, 2 * radius, 2 * radius)

    def _paint_magnify(self, p, color, base):
        """A loupe: the picked area at 2x in a circle, tied to its source."""
        r = self.rect.normalized()
        lens = self._lens()
        p.setPen(QtGui.QPen(color, 2, QtCore.Qt.PenStyle.DashLine))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)              # no frame round the source: a dashed line only
        p.drawLine(r.center(), lens.center() - QtCore.QPointF(
            (lens.center() - r.center()).x() * (lens.width() / 2) / max(1.0, math.hypot(*(lens.center() - r.center()).toTuple())),
            (lens.center() - r.center()).y() * (lens.width() / 2) / max(1.0, math.hypot(*(lens.center() - r.center()).toTuple()))))
        if base is not None and r.width() > 1 and r.height() > 1:
            dpr = base.devicePixelRatio()
            side = max(r.width(), r.height())
            src = QtCore.QRectF(r.center().x() - side / 2, r.center().y() - side / 2, side, side)
            clip = QtGui.QPainterPath()
            clip.addEllipse(lens)
            p.save()
            p.setClipPath(clip, QtCore.Qt.ClipOperation.IntersectClip)
            p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawPixmap(lens, base, QtCore.QRectF(src.x() * dpr, src.y() * dpr, src.width() * dpr, src.height() * dpr))
            p.restore()
        p.setPen(QtGui.QPen(color, max(3.0, self.width * 0.8)))
        p.drawEllipse(lens)

    def _paint_counter(self, p, color, _base):
        r = self.radius()
        c = self.points[0]
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 230), max(1.5, r * 0.09)))
        p.setBrush(color)
        p.drawEllipse(c, r, r)
        font = QtGui.QFont("Segoe UI")
        font.setPixelSize(int(r * 1.15))
        font.setBold(True)
        p.setFont(font)
        light = color.lightnessF() > 0.7
        p.setPen(QtGui.QColor("#111111" if light else "#ffffff"))
        p.drawText(QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), QtCore.Qt.AlignmentFlag.AlignCenter,
                   str(self.number))
        if self.text:                                      # its note, in the number's colour, outlined
            rect = self.text_rect()
            inner = rect.adjusted(2, 2, 0, 0)
            metrics = QtGui.QFontMetricsF(self.qfont())
            path = QtGui.QPainterPath()
            for i, line in enumerate(self.text.split("\n")):
                path.addText(inner.x(), inner.y() + metrics.ascent() + i * metrics.lineSpacing(), self.qfont(), line)
            p.setPen(QtGui.QPen(QtGui.QColor(self.outline or "#000000"), max(2.0, self.width * 0.7),
                                QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap,
                                QtCore.Qt.PenJoinStyle.RoundJoin))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPath(path)

    def _crop(self, base):
        rect = self.rect.normalized()
        if base is None or rect.width() < 2 or rect.height() < 2:
            return None, rect
        dpr = base.devicePixelRatio()
        return base.copy(QtCore.QRect(int(rect.x() * dpr), int(rect.y() * dpr),
                                      int(rect.width() * dpr), int(rect.height() * dpr))), rect

    def _paint_blur(self, p, _color, base):
        """A real blur: down and back up with smooth filtering, twice - soft,
        no blocks (Pixelate is its own tool)."""
        src, rect = self._crop(base)
        if src is None:
            return
        k = max(2.0, self.width * 1.5)
        img = src
        for _ in range(2):
            small = img.scaled(max(1, int(src.width() / k)), max(1, int(src.height() / k)),
                               QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                               QtCore.Qt.TransformationMode.SmoothTransformation)
            img = small.scaled(src.width(), src.height(), QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                               QtCore.Qt.TransformationMode.SmoothTransformation)
        p.setOpacity(1.0)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(rect, img, QtCore.QRectF(img.rect()))

    def _paint_pixelate(self, p, _color, base):
        src, rect = self._crop(base)
        if src is None:
            return
        block = max(4, int(self.width * 2))
        small = src.scaled(max(1, int(src.width() / block)), max(1, int(src.height() / block)),
                           QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                           QtCore.Qt.TransformationMode.SmoothTransformation)
        p.setOpacity(1.0)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawPixmap(rect, small, QtCore.QRectF(small.rect()))

    def _paint_poly(self, p, color, _base):
        """The lasso's fill - or its cut, when it erases."""
        path = QtGui.QPainterPath()
        path.addPolygon(QtGui.QPolygonF(self.points))
        path.closeSubpath()
        if self.erase:
            p.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_DestinationOut)
            color = QtGui.QColor(0, 0, 0)
        p.fillPath(path, color)

    def _paint_image(self, p, _color, _base):
        if self.image is not None and self.warp:              # the picture bent over the mesh
            # textured triangles, antialiasing off: neighbours share edges exactly - no seams, no
            # doubled alpha (overlapping quads left little crosses on soft strokes)
            if getattr(self, "_tex_src", None) is not self.image:
                tex = self.image.toImage()
                tex.setDevicePixelRatio(1.0)
                self._tex, self._tex_src = QtGui.QPixmap.fromImage(tex), self.image
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
            p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            n = 16
            grid = self.warp_grid(n)
            iw, ih = self._tex.width(), self._tex.height()
            brush = QtGui.QBrush(self._tex)
            for j in range(n):
                for i in range(n):
                    s00 = (iw * i / n, ih * j / n)
                    s10 = (iw * (i + 1) / n, ih * j / n)
                    s11 = (iw * (i + 1) / n, ih * (j + 1) / n)
                    s01 = (iw * i / n, ih * (j + 1) / n)
                    d00, d10, d11, d01 = grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]
                    for (sa, sb, sc), (da, db, dc) in (((s00, s10, s11), (d00, d10, d11)),
                                                       ((s00, s11, s01), (d00, d11, d01))):
                        t = _affine(sa, sb, sc, da, db, dc)
                        if t is None:
                            continue
                        brush.setTransform(t)
                        p.setBrush(brush)
                        p.drawPolygon(QtGui.QPolygonF([da, db, dc]))
            return
        if self.image is not None:
            p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawPixmap(self.rect.normalized(), self.image, QtCore.QRectF(self.image.rect()))
            if self.raster:
                return
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 90), 1))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawRect(self.rect.normalized())

    # -- save / load -------------------------------------------------------
    def to_dict(self) -> dict:
        d = {"kind": self.kind, "color": self.color.name(QtGui.QColor.NameFormat.HexArgb),
             "width": self.width, "opacity": self.opacity,
             "points": [[p.x(), p.y()] for p in self.points],
             "rect": [self.rect.x(), self.rect.y(), self.rect.width(), self.rect.height()],
             "text": self.text, "font": self.font, "box": self.box, "number": self.number,
             "brush": self.brush, "seed": self.seed, "flow": self.flow, "erase": self.erase, "angle": self.angle,
             "outline": self.outline}
        if not self.xform.isIdentity():
            x = self.xform
            d["xf"] = [x.m11(), x.m12(), x.m13(), x.m21(), x.m22(), x.m23(), x.m31(), x.m32(), x.m33()]
        d["layer"] = self.layer
        if self.warp:
            d["warp"] = [list(c) for c in self.warp]
        d["raster"] = self.raster
        d["shot"] = self.shot
        if self.cuts:
            d["cuts"] = [c.to_dict() for c in self.cuts]
        if self.image is not None:
            buf = QtCore.QBuffer()
            buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
            self.image.save(buf, "PNG")
            d["image"] = base64.b64encode(bytes(buf.data())).decode()     # a pasted picture as PNG text in the history JSON
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Shape":
        kind = d["kind"]
        brush = d.get("brush", "pen")
        if kind in ("pen", "marker"):                  # version 0.1 marks
            kind, brush = "stroke", "pen" if kind == "pen" else "highlighter"
        s = cls(kind, d.get("color", "#ff3b30"), d.get("width", 4), d.get("opacity", 1.0))
        s.brush, s.seed = brush, int(d.get("seed", 0))        # an old brush id falls back to the first
        s.angle = float(d.get("angle", 0.0))
        s.flow = float(d.get("flow", 1.0))
        s.erase = bool(d.get("erase"))
        s.outline = d.get("outline", "#000000")
        s.points = [QtCore.QPointF(x, y) for x, y in d.get("points", [])]
        s.rect = QtCore.QRectF(*d.get("rect", [0, 0, 0, 0]))
        s.text, s.font = d.get("text", ""), d.get("font", "Segoe UI")
        s.box, s.number = bool(d.get("box")), int(d.get("number", 1))
        if d.get("xf"):
            xf = d["xf"]                                   # 6 values (old, affine) or 9 (with perspective)
            s.xform = QtGui.QTransform(*xf) if len(xf) == 9 else \
                QtGui.QTransform(xf[0], xf[1], 0, xf[2], xf[3], 0, xf[4], xf[5], 1)
        s.layer = d.get("layer", "")
        s.warp = [tuple(c) for c in d["warp"]] if d.get("warp") else None
        s.raster = bool(d.get("raster"))
        s.shot = bool(d.get("shot"))
        s.cuts = [cls.from_dict(c) for c in d.get("cuts", [])]
        if d.get("image"):
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(base64.b64decode(d["image"]), "PNG")
            s.image = pixmap
        return s


def _affine(sa, sb, sc, da, db, dc):
    """The affine map taking triangle (sa, sb, sc) - plain (x, y) - onto (da, db, dc) - QPointF."""
    (x1, y1), (x2, y2), (x3, y3) = sa, sb, sc
    det = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
    if abs(det) < 1e-9:
        return None
    u = ((da.x(), da.y()), (db.x(), db.y()), (dc.x(), dc.y()))
    out = []
    for k in range(2):
        v1, v2, v3 = u[0][k], u[1][k], u[2][k]
        a = ((v2 - v1) * (y3 - y1) - (v3 - v1) * (y2 - y1)) / det
        b = ((v3 - v1) * (x2 - x1) - (v2 - v1) * (x3 - x1)) / det
        out.append((a, b, v1 - a * x1 - b * y1))
    (a, b, c), (d, e, f) = out
    return QtGui.QTransform(a, d, b, e, c, f)


def _dist(a, b) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _dist_to_segment(p, a, b) -> float:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    if dx == dy == 0:
        return _dist(p, a)
    t = max(0.0, min(1.0, ((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p.x() - (a.x() + t * dx), p.y() - (a.y() + t * dy))


def _smooth(points) -> QtGui.QPainterPath:
    """Quadratic midpoint smoothing: a mouse stroke without the jaggies."""
    path = QtGui.QPainterPath()
    if not points:
        return path
    path.moveTo(points[0])
    if len(points) < 3:
        for pt in points[1:]:
            path.lineTo(pt)
        return path
    for a, b in zip(points[1:-1], points[2:]):
        mid = QtCore.QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
        path.quadTo(a, mid)
    path.lineTo(points[-1])
    return path


def constrain(a: QtCore.QPointF, b: QtCore.QPointF) -> QtCore.QPointF:
    """Shift: snap a line to 45 degrees."""
    angle = math.atan2(b.y() - a.y(), b.x() - a.x())
    snapped = round(angle / (math.pi / 4)) * (math.pi / 4)
    length = _dist(a, b)
    return QtCore.QPointF(a.x() + math.cos(snapped) * length, a.y() + math.sin(snapped) * length)

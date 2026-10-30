"""The panel: capture, your folders, links (each in the browser / Chrome
profile it belongs to), programs, quick notes and the screenshot history.
Everything you add stays until you delete it - and is yours to arrange:
a colour label, a size (what matters is bigger), your own icon, and filter
chips (Work, YouTube...) across every list."""
import datetime
import os
import re
import subprocess

from PySide6 import QtCore, QtGui, QtWidgets

from . import store, theme, winsys

ROLE = QtCore.Qt.ItemDataRole.UserRole
SIZES = {"s": (24, 16), "m": (34, 22), "l": (52, 38)}          # row height, icon side
LABELS = ("#e5534b", "#f28c28", "#e8c547", "#57ab5a", "#39a0d9", "#986ee2", "#d06bb0", "#8a8a8a")
KINDS = {"Folders": "folders", "Links": "links", "Programs": "programs", "Notes": "notes"}


# --------------------------------------------------------------------- icons
#: emblems for a folder (the glyph on its front) - the quick library, like Windows' folder icons
EMBLEMS = ("image", "film-strip", "music-notes", "camera", "video-camera", "palette", "paint-brush", "cube",
           "game-controller", "code", "bug", "wrench", "file-text", "book-open", "graduation-cap", "briefcase",
           "archive", "download-simple", "cloud", "desktop", "house", "users-three", "lock-key", "star", "heart",
           "fire", "lightbulb", "rocket-launch", "airplane", "shopping-cart")


def item_icon(kind: str, entry: dict, side: int) -> QtGui.QIcon:
    custom = entry.get("icon") or ""
    if "|" in custom:                                     # an icon out of a Windows library: "file|index"
        path, _, idx = custom.rpartition("|")
        image = winsys.file_icon(path, int(idx or 0), max(32, side * 2)) if os.path.isfile(path) else None
        if image is not None and not image.isNull():
            return QtGui.QIcon(QtGui.QPixmap.fromImage(image))
    elif custom and os.path.isfile(custom):
        if custom.lower().endswith((".exe", ".lnk", ".ico", ".dll")):
            return QtWidgets.QFileIconProvider().icon(QtCore.QFileInfo(custom))
        return QtGui.QIcon(custom)
    color = entry.get("color") or ""
    if entry.get("folder"):                               # a folder among the notes
        return QtGui.QIcon(theme.folder_pixmap(side, color, entry.get("emblem") or ""))
    if entry.get("emblem") and kind != "folders":         # a glyph from the library instead of the app's
        return theme.icon(entry["emblem"], side, color or "#c9bba6")
    if kind == "folders":
        return QtGui.QIcon(theme.folder_pixmap(side, color, entry.get("emblem") or ""))
    if kind == "links":
        return theme.icon("globe", side, color or "#7fb2ff")
    if kind == "programs":
        exe = entry.get("exe", "")
        if os.path.exists(exe):
            return QtWidgets.QFileIconProvider().icon(QtCore.QFileInfo(exe))
        return theme.icon("app-window", side, color or "#bdbdbd")
    return theme.icon("note-pencil", side, color or "#9ad08a")


# --------------------------------------------------------------------- one row
class RowDelegate(QtWidgets.QStyledItemDelegate):
    """Each row its own size (bigger = more important) and colour label."""

    TILE = QtCore.QSize(88, 84)

    @staticmethod
    def _tiles(option) -> bool:
        w = option.widget
        return isinstance(w, QtWidgets.QListView) and w.viewMode() == QtWidgets.QListView.ViewMode.IconMode

    def sizeHint(self, option, index):                          # noqa: N802
        if self._tiles(option):
            return self.TILE
        size = SIZES.get(index.data(ROLE + 1) or "m", SIZES["m"])
        return QtCore.QSize(option.rect.width(), size[0])

    def paint(self, p, option, index):
        if self._tiles(option):
            self._paint_tile(p, option, index)
            return
        p.save()
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        r = QtCore.QRectF(option.rect).adjusted(1, 1, -1, -1)
        state = option.state
        if state & QtWidgets.QStyle.StateFlag.State_Selected:
            p.setBrush(QtGui.QColor("#4a3420"))
        elif state & QtWidgets.QStyle.StateFlag.State_MouseOver:
            p.setBrush(QtGui.QColor("#383838"))
        else:
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 4, 4)
        color = index.data(ROLE + 2)
        if color:                                                     # the colour label
            p.setBrush(QtGui.QColor(color))
            p.drawRoundedRect(QtCore.QRectF(r.left() + 2, r.top() + 4, 3, r.height() - 8), 1.5, 1.5)
        size = SIZES.get(index.data(ROLE + 1) or "m", SIZES["m"])
        icon = index.data(QtCore.Qt.ItemDataRole.DecorationRole)
        side = size[1]
        fold = index.data(ROLE + 4) or ""                  # "open" / "closed" on a notes folder
        left = r.left() + 10 + (24 if index.data(ROLE + 5) else 0)
        if fold:                                           # the scroll's caret
            cx, cy = left + 4, r.center().y()
            caret = QtGui.QPolygonF([QtCore.QPointF(cx - 4, cy - 2), QtCore.QPointF(cx + 4, cy - 2),
                                     QtCore.QPointF(cx, cy + 3)] if fold == "open" else
                                    [QtCore.QPointF(cx - 2, cy - 4), QtCore.QPointF(cx - 2, cy + 4),
                                     QtCore.QPointF(cx + 3, cy)])
            p.setBrush(QtGui.QColor("#9a9a9a"))
            p.drawPolygon(caret)
            left += 14
        icon_rect = QtCore.QRect(int(left), int(r.center().y() - side / 2), side, side)
        if isinstance(icon, QtGui.QIcon):
            icon.paint(p, icon_rect)
        font = QtGui.QFont(option.font)
        font.setPixelSize({"s": 12, "m": 13, "l": 16}.get(index.data(ROLE + 1) or "m", 13))
        font.setBold((index.data(ROLE + 1) or "m") == "l")
        p.setFont(font)
        p.setPen(QtGui.QColor("#e8e8e8"))
        text_rect = QtCore.QRectF(icon_rect.right() + 10, r.top(), r.right() - icon_rect.right() - 14, r.height())
        tags = index.data(ROLE + 3) or ""
        name = QtGui.QFontMetrics(font).elidedText(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
                                                   QtCore.Qt.TextElideMode.ElideRight, int(text_rect.width()))
        p.drawText(text_rect, QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignLeft, name)
        if tags:                                                       # its filters, quiet, on the right
            small = QtGui.QFont(option.font)
            small.setPixelSize(10)
            p.setFont(small)
            p.setPen(QtGui.QColor("#8a8a8a"))
            p.drawText(text_rect, QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight, tags)
        p.restore()


    def _paint_tile(self, p, option, index):
        """A tile: the icon big, a short name under it."""
        p.save()
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        r = QtCore.QRectF(option.rect).adjusted(2, 2, -2, -2)
        state = option.state
        if state & QtWidgets.QStyle.StateFlag.State_Selected:
            p.setBrush(QtGui.QColor("#4a3420"))
        elif state & QtWidgets.QStyle.StateFlag.State_MouseOver:
            p.setBrush(QtGui.QColor("#383838"))
        else:
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 6, 6)
        color = index.data(ROLE + 2)
        if color:                                                     # the colour label: a bar on top
            p.setBrush(QtGui.QColor(color))
            p.drawRoundedRect(QtCore.QRectF(r.center().x() - 14, r.top() + 2, 28, 3), 1.5, 1.5)
        side = 40
        icon = index.data(QtCore.Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QtGui.QIcon):
            icon.paint(p, QtCore.QRect(int(r.center().x() - side / 2), int(r.top() + 9), side, side))
        if index.data(ROLE + 4):                                      # a notes folder: open / closed mark
            p.setBrush(QtGui.QColor("#9a9a9a"))
            cx, cy = r.right() - 10, r.top() + 12
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(cx - 4, cy - 2), QtCore.QPointF(cx + 4, cy - 2),
                                           QtCore.QPointF(cx, cy + 3)] if index.data(ROLE + 4) == "open" else
                                          [QtCore.QPointF(cx - 2, cy - 4), QtCore.QPointF(cx - 2, cy + 4),
                                           QtCore.QPointF(cx + 3, cy)]))
        font = QtGui.QFont(option.font)
        font.setPixelSize(11)
        p.setFont(font)
        p.setPen(QtGui.QColor("#e8e8e8"))
        text_rect = QtCore.QRectF(r.left() + 4, r.top() + 54, r.width() - 8, 18)
        name = QtGui.QFontMetrics(font).elidedText(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
                                                   QtCore.Qt.TextElideMode.ElideRight, int(text_rect.width()))
        p.drawText(text_rect, QtCore.Qt.AlignmentFlag.AlignCenter, name)
        p.restore()


# --------------------------------------------------------------------- filters
def filters() -> list:
    return store.get("filters")


def matches(flt: dict, entry: dict) -> bool:
    """Tagged by hand - or a word of the filter found in its name / address."""
    if flt["id"] in (entry.get("tags") or []):
        return True
    words = [w.strip().lower() for w in (flt.get("match") or flt["name"]).split(",") if w.strip()]
    hay = " ".join(str(entry.get(k, "")) for k in ("name", "url", "path", "exe", "title", "text")).lower()
    return any(w in hay for w in words)


class Chips(QtWidgets.QWidget):
    """The filter chips: All + yours. Right click to add / edit / delete."""
    changed = QtCore.Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.current = ""
        self.setObjectName("ltChips")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#ltChips { background: transparent; }")
        self.row = QtWidgets.QHBoxLayout(self)
        self.row.setContentsMargins(0, 2, 0, 2)
        self.row.setSpacing(4)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self._menu(None, self.mapToGlobal(pos)))
        self.rebuild()

    def rebuild(self) -> None:
        while self.row.count():
            w = self.row.takeAt(0).widget()
            if w:
                w.deleteLater()
        for fid, name in [("", "All")] + [(f["id"], f["name"]) for f in filters()]:
            b = QtWidgets.QToolButton()
            b.setText(name)
            b.setCheckable(True)
            b.setChecked(fid == self.current)
            b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            b.setStyleSheet("QToolButton { background: #2b2b2b; border: 1px solid #3d3d3d; border-radius: 10px;"
                            " padding: 2px 10px; color: #cfcfcf; }"
                            f"QToolButton:checked {{ background: #4a3420; border-color: {theme.ACCENT}; color: #fff; }}")
            b.clicked.connect(lambda _c=False, f=fid: self._pick(f))
            if fid:
                b.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda pos, f=fid, w=b: self._menu(f, w.mapToGlobal(pos)))
            self.row.addWidget(b)
        add = QtWidgets.QToolButton()
        add.setIcon(theme.icon("plus", 12, "#9a9a9a"))
        add.setToolTip("New filter (Work, YouTube...) - right click a chip to edit it")
        add.clicked.connect(self.new_filter)
        add.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.row.addWidget(add)
        self.row.addStretch(1)

    def _pick(self, fid: str) -> None:
        self.current = fid
        self.rebuild()
        self.changed.emit()

    def new_filter(self) -> None:
        dialog = FilterDialog(self.window())
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            items = filters()
            items.append(dict(dialog.value(), id=store.new_id()))
            store.put("filters", items)
            self.rebuild()
            self.changed.emit()

    def _menu(self, fid, at) -> None:
        menu = QtWidgets.QMenu(self)
        if fid:
            entry = next(f for f in filters() if f["id"] == fid)
            menu.addAction(theme.icon("pencil-simple"), "Edit Filter", lambda: self._edit(entry))
            menu.addAction(theme.icon("trash"), "Delete Filter", lambda: self._delete(fid))
            menu.addSeparator()
        menu.addAction(theme.icon("plus"), "New Filter", self.new_filter)
        menu.exec(at)

    def _edit(self, entry) -> None:
        dialog = FilterDialog(self.window(), entry)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            entry.update(dialog.value())
            store.save()
            self.rebuild()
            self.changed.emit()

    def _delete(self, fid) -> None:
        store.put("filters", [f for f in filters() if f["id"] != fid])
        for key in KINDS.values():
            for entry in store.get(key):
                if fid in (entry.get("tags") or []):
                    entry["tags"].remove(fid)
        store.save()
        if self.current == fid:
            self.current = ""
        self.rebuild()
        self.changed.emit()


class FilterDialog(QtWidgets.QDialog):
    def __init__(self, parent, entry=None):
        super().__init__(parent)
        self.setWindowTitle("Filter")
        self.setStyleSheet(theme.STYLE)
        form = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit(entry["name"] if entry else "")
        self.name.setPlaceholderText("Work")
        self.match = QtWidgets.QLineEdit(entry.get("match", "") if entry else "")
        self.match.setPlaceholderText("work, docs  (empty = the name)")
        self.match.setToolTip("An item shows under this filter when one of these words is in its name or "
                              "address - or when you tag it by hand (right click > Filters)")
        form.addRow("Name", self.name)
        form.addRow("Matches", self.match)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(lambda: self.accept() if self.name.text().strip() else self.name.setFocus())
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(380, 0)

    def value(self) -> dict:
        return {"name": self.name.text().strip(), "match": self.match.text().strip()}


# --------------------------------------------------------------------- the panel
class Launcher(QtWidgets.QWidget):
    def __init__(self, app):
        super().__init__(None, QtCore.Qt.WindowType.Window)
        self.app = app
        self.setObjectName("ltLauncher")
        from . import __version__
        self.setWindowTitle(f"Lead Tool {__version__}")            # the version in sight: which one is installed
        self.setWindowIcon(theme.app_icon())
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.STYLE)
        self.setMinimumSize(450, 380)
        self.setAcceptDrops(True)
        col = QtWidgets.QVBoxLayout(self)
        col.setContentsMargins(8, 8, 8, 8)
        col.setSpacing(6)

        # a plain row of tools - the screenshot is one of them, not a billboard
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(2)
        # a real button you can hit - sized to its words, not a banner
        shot = QtWidgets.QPushButton(theme.icon("camera", 18, theme.ACCENT), "  Screenshot")
        shot.setToolTip(f"Capture an area  ({store.get('hotkeys')['capture']})")
        shot.setFixedHeight(34)
        shot.setStyleSheet("QPushButton { padding: 4px 16px; font-weight: bold; }")
        shot.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        shot.clicked.connect(lambda: self.app.capture(from_panel=True))
        bar.addWidget(shot)
        # the report: words too - an icon alone read like "copy"
        rep = QtWidgets.QPushButton(theme.icon("presentation-chart", 18, "#86a8c8"), "  Report")
        rep.setToolTip("Create a report: screenshots in a row, TASK / ASSET / STAGE")
        rep.setFixedHeight(34)
        rep.setStyleSheet("QPushButton { padding: 4px 14px; }")
        rep.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        rep.clicked.connect(lambda: self.app.open_report())
        bar.addWidget(rep)
        bar.addSpacing(6)
        for icon, tip, slot in (
                ("clock-counter-clockwise", "Same area again", lambda: self.app.capture(repeat=True, from_panel=True)),
                ("note-pencil", "Quick note", self.app.new_note),
                ("clipboard-text", "Clipboard history - click one to copy it again", self._clips)):
            bar.addWidget(self._tool(icon, tip, slot))
        bar.addStretch(1)
        self.top_btn = self._tool("push-pin", "Always on top", self._toggle_top, checkable=True)
        self.top_btn.setChecked(bool(store.get("launcher_on_top")))
        bar.addWidget(self.top_btn)
        bar.addWidget(self._tool("gear", "Settings", self.app.settings))
        col.addLayout(bar)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.lists = {}
        for title, icon in (("Folders", "folder"), ("Links", "link"), ("Programs", "app-window"),
                            ("Notes", "note-pencil")):
            self.lists[title] = self._list_page(title, icon)
        self.history = QtWidgets.QListWidget()
        self.history.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.history.setIconSize(QtCore.QSize(120, 80))
        self.history.setGridSize(QtCore.QSize(132, 104))
        self.history.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.history.setMovement(QtWidgets.QListView.Movement.Static)
        self.history.itemDoubleClicked.connect(lambda it: self.app.reopen(it.data(ROLE)))
        self.history.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self._history_menu)
        page = QtWidgets.QWidget()                    # laid out like the other tabs: same margins, same bottom row
        hcol = QtWidgets.QVBoxLayout(page)
        hcol.setContentsMargins(0, 6, 0, 0)
        hcol.addWidget(self.history, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        current = lambda: self.history.currentItem().data(ROLE) if self.history.currentItem() else None
        row.addWidget(self._tool("pencil-simple", "Open and Draw", lambda: current() and self.app.reopen(current())))
        row.addWidget(self._tool("trash", "Delete", lambda: current() and self._delete_history(current())))
        hcol.addLayout(row)
        self.tabs.addTab(page, theme.icon("image", 14), "History")
        self.chips = Chips(self)
        self.chips.changed.connect(self.refresh)
        keep = self.chips.sizePolicy()
        keep.setRetainSizeWhenHidden(True)            # History hides the filters but keeps their place: no jump
        self.chips.setSizePolicy(keep)
        self.tabs.currentChanged.connect(lambda _i: self.chips.setVisible(self.tabs.currentWidget() is not page))
        col.addWidget(self.chips)
        col.addWidget(self.tabs, 1)
        for title in self.lists:
            self._apply_view(title)
        self.refresh()
        self._apply_top()
        geo = store.get("launcher_geometry")
        if geo:
            self.setGeometry(*geo)
        else:
            self.resize(470, 580)

    def dragEnterEvent(self, e):                                  # noqa: N802
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):                                       # noqa: N802
        self.add_things(self._things(e.mimeData()))
        e.acceptProposedAction()

    # ------------------------------------------------------------ building
    def _tool(self, icon, tip, slot, checkable=False):
        b = QtWidgets.QToolButton()
        b.setIcon(theme.icon(icon, 18))
        b.setIconSize(QtCore.QSize(18, 18))
        b.setFixedSize(32, 32)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        b.clicked.connect(slot)
        return b

    def _list_page(self, title, icon):
        page = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(page)
        col.setContentsMargins(0, 6, 0, 0)
        lst = QtWidgets.QListWidget()
        lst.setItemDelegate(RowDelegate(lst))
        lst.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)   # Ctrl / Shift, as in Explorer
        lst.viewport().installEventFilter(self)          # drops from outside (Explorer, a browser)
        lst.installEventFilter(self)                     # Ctrl+V adds what is copied
        lst.setMouseTracking(True)
        lst.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DropOnly)   # rows move by _drag_rows
        # double click OPENS; renaming is F2 or right click > Rename
        lst.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
        lst.itemActivated.connect(lambda it, t=title: self._open(t, it))
        lst.itemClicked.connect(lambda it, t=title: self._fold(t, it))
        lst.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        lst.customContextMenuRequested.connect(lambda pos, t=title, l=lst: self._menu(t, l, pos))
        lst.setProperty("lt_title", title)
        mark = QtWidgets.QFrame(lst.viewport())          # where the dragged row will land
        mark.setStyleSheet(f"background: {theme.ACCENT}; border: none;")
        mark.hide()
        lst.setProperty("lt_mark", mark)
        lst.itemChanged.connect(lambda it, t=title: self._renamed(t, it))
        col.addWidget(lst, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        view = self._tool("squares-four", "Tiles / list  (this tab)", lambda _c=False, t=title: self._toggle_view(t))
        row.insertWidget(0, view)                        # left, away from add / edit / delete
        row.addWidget(self._tool("folder", "New Folder", lambda _c=False, t=title: self.new_group(t)))
        row.addWidget(self._tool("plus", f"Add to {title}", lambda _c=False, t=title: self._add(t)))
        row.addWidget(self._tool("pencil-simple", "Rename / edit", lambda _c=False, t=title, l=lst: self._edit(t, l.currentItem())))
        row.addWidget(self._tool("trash", "Delete", lambda _c=False, t=title, l=lst: self._delete(t, l.currentItem())))
        col.addLayout(row)
        self.tabs.addTab(page, theme.icon(icon, 14), title)
        return lst

    def refresh(self) -> None:
        names = {f["id"]: f["name"] for f in filters()}
        current = next((f for f in filters() if f["id"] == self.chips.current), None)
        for title, lst in self.lists.items():
            kind = KINDS[title]
            lst.blockSignals(True)
            lst.clear()
            entries = store.get(kind)
            if current is None:                            # groups, each with its items under it when open
                ids = {x["id"] for x in entries if x.get("folder")}
                ordered = []
                for x in entries:
                    if x.get("parent") in ids:
                        continue
                    ordered.append((x, 0))
                    if x.get("folder") and x.get("open", True):
                        ordered += [(c, 1) for c in entries if c.get("parent") == x["id"]]
            else:
                ordered = [(x, 0) for x in entries if not x.get("folder")]
            for entry, depth in ordered:
                if current is not None and not matches(current, entry):
                    continue
                size = SIZES.get(entry.get("size") or "m", SIZES["m"])
                label = entry.get("name") or entry.get("title") or (entry.get("text") or "").split("\n")[0][:60]
                it = QtWidgets.QListWidgetItem(item_icon(kind, entry, size[1]), label)
                it.setData(ROLE, entry["id"])
                it.setData(ROLE + 1, entry.get("size") or "m")
                it.setData(ROLE + 2, entry.get("color") or "")
                it.setData(ROLE + 3, "  ".join(names[t] for t in entry.get("tags") or [] if t in names))
                it.setToolTip(entry.get("path") or entry.get("url") or entry.get("exe")
                              or (entry.get("text") or "")[:400])
                it.setFlags(it.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
                if entry.get("folder"):
                    it.setData(ROLE + 4, "open" if entry.get("open", True) else "closed")
                    it.setToolTip("")
                it.setData(ROLE + 5, depth)
                lst.addItem(it)
            lst.blockSignals(False)
        self.refresh_history()

    def refresh_history(self) -> None:
        self.history.clear()
        folder = store.history_dir()
        for h in store.get("history"):
            path = os.path.join(folder, h["id"] + ".png")
            if not os.path.isfile(path):
                continue
            pixmap = QtGui.QPixmap(path).scaled(240, 160, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                                QtCore.Qt.TransformationMode.SmoothTransformation)
            when = h.get("created", "").replace("T", " ")[5:16]
            it = QtWidgets.QListWidgetItem(QtGui.QIcon(pixmap), when)
            it.setData(ROLE, h["id"])
            it.setToolTip("Double click: open and draw again  ·  right click: more")
            self.history.addItem(it)

    # ------------------------------------------------------------ actions
    def _find(self, title, item):
        if item is None:
            return None
        return next((x for x in store.get(KINDS[title]) if x["id"] == item.data(ROLE)), None)

    def _open(self, title, item) -> None:
        entry = self._find(title, item)
        if entry is None:
            return
        if entry.get("folder"):                            # a group opens with one click (_fold)
            return
        if title == "Folders":
            if os.path.isdir(entry["path"]):
                winsys.open_path(entry["path"])
            else:
                self.app.toast(f"Folder not found: {entry['path']}")
        elif title == "Links":
            winsys.open_url(entry["url"], entry.get("browser", ""))
        elif title == "Programs":
            self._run(entry)
        else:
            self.app.open_note(entry["id"])

    # ------------------------------------------------------------ drop / paste to add
    def eventFilter(self, obj, e):                                # noqa: N802
        t = e.type()
        E = QtCore.QEvent.Type
        if t in (E.MouseButtonPress, E.MouseMove, E.MouseButtonRelease, E.MouseButtonDblClick) and isinstance(
                obj.parent(), QtWidgets.QListWidget) and obj.parent().property("lt_title"):
            if self._drag_rows(obj.parent(), e):
                return True
        if t in (E.DragEnter, E.DragMove) and e.source() is None and (e.mimeData().hasUrls() or e.mimeData().hasText()):
            e.acceptProposedAction()
            return True
        if t == E.Drop and e.source() is None:
            self.add_things(self._things(e.mimeData()))
            e.acceptProposedAction()
            return True
        if t == E.KeyPress and e.matches(QtGui.QKeySequence.StandardKey.Paste) \
                and isinstance(obj, QtWidgets.QListWidget) and obj.state() != QtWidgets.QAbstractItemView.State.EditingState:
            self.add_things(self._things(QtWidgets.QApplication.clipboard().mimeData()), paste=True)
            return True
        return super().eventFilter(obj, e)

    def _clips(self) -> None:
        self.app.clips.menu(self).exec(QtGui.QCursor.pos())

    def _copy_of(self, title, item) -> None:
        """Ctrl+click: the item's path / address on the clipboard."""
        entry = self._find(title, item)
        if entry is None or entry.get("folder"):
            return
        text = entry.get("path") or entry.get("url") or entry.get("exe") or entry.get("text") or ""
        if text:
            QtWidgets.QApplication.clipboard().setText(text)
            self.app.toast("Copied: " + (text if len(text) < 70 else text[:67] + "…"))

    def _drag_rows(self, lst, e) -> bool:
        """Press a row, drag, let go: it moves there (a line shows where).
        True = the event is used (the release of a drag is no click)."""
        E = QtCore.QEvent.Type
        pos = e.position().toPoint()
        mark = lst.property("lt_mark")
        if e.type() == E.MouseButtonDblClick and e.button() == QtCore.Qt.MouseButton.LeftButton:
            item = lst.itemAt(pos)                          # double click opens - list or tiles alike
            if item is not None:                            # (tiles never got Qt's activated: links did not open)
                self._rows = None
                self._open(lst.property("lt_title"), item)
                return True
            return False
        if e.type() == E.MouseButtonPress and e.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier                 and e.button() == QtCore.Qt.MouseButton.LeftButton and lst.itemAt(pos) is not None:
            self._copy_of(lst.property("lt_title"), lst.itemAt(pos))
            return True
        if e.type() == E.MouseButtonPress:
            item = lst.itemAt(pos) if e.button() == QtCore.Qt.MouseButton.LeftButton else None
            self._rows = (lst, pos, lst.row(item), False) if item is not None else None
            return False
        rows = getattr(self, "_rows", None)
        if rows is None or rows[0] is not lst or lst.state() == QtWidgets.QAbstractItemView.State.EditingState:
            return False
        _l, start, src, moving = rows
        if e.type() == E.MouseMove:
            if not e.buttons() & QtCore.Qt.MouseButton.LeftButton:
                self._rows = None
                mark.hide()
                return False
            if not moving and (pos - start).manhattanLength() < QtWidgets.QApplication.startDragDistance():
                return False
            self._rows = (lst, start, src, True)
            target, line = self._drop_slot(lst, pos)
            mark.setGeometry(line)
            mark.show()
            mark.raise_()
            return True
        # release
        self._rows = None
        mark.hide()
        if not moving:
            return False
        target, _line = self._drop_slot(lst, pos)
        to = target if target <= src else target - 1
        if to != src:
            item = lst.takeItem(src)
            lst.insertItem(to, item)
            lst.setCurrentItem(item)
            self._reordered(lst.property("lt_title"), lst, to)
        return True

    @staticmethod
    def _drop_slot(lst, pos):
        """(the row it goes before, the line to show there)."""
        tiles = lst.viewMode() == QtWidgets.QListView.ViewMode.IconMode
        item = lst.itemAt(pos)
        if item is None:
            last = lst.item(lst.count() - 1)
            if last is None:
                return 0, QtCore.QRect()
            r = lst.visualItemRect(last)
            return lst.count(), (QtCore.QRect(r.right() - 1, r.top() + 4, 3, r.height() - 8) if tiles
                                 else QtCore.QRect(r.left() + 4, r.bottom() - 1, r.width() - 8, 3))
        r = lst.visualItemRect(item)
        after = pos.x() > r.center().x() if tiles else pos.y() > r.center().y()
        row = lst.row(item) + (1 if after else 0)
        if tiles:
            x = r.right() if after else r.left()
            return row, QtCore.QRect(x - 1, r.top() + 4, 3, r.height() - 8)
        y = r.bottom() if after else r.top()
        return row, QtCore.QRect(r.left() + 4, y - 1, r.width() - 8, 3)

    @staticmethod
    def _things(mime) -> list:
        """What was dropped / copied: local paths and web addresses."""
        out = []
        for url in mime.urls() if mime.hasUrls() else []:
            out.append(url.toLocalFile() if url.isLocalFile() else url.toString())
        if not out and mime.hasText():
            out = [line.strip().strip('"') for line in mime.text().splitlines() if line.strip()]
        return out

    def add_things(self, things, paste=False) -> None:
        """A folder -> Folders, a program -> Programs, an address -> Links."""
        import re
        added = {}
        current = self.tabs.tabText(self.tabs.currentIndex())
        for thing in things:
            path = os.path.normpath(thing) if re.match(r"^[A-Za-z]:[\\/]|^\\\\", thing) else ""
            if path and os.path.isdir(path):
                title, entry = "Folders", {"name": os.path.basename(path.rstrip("\\")) or path, "path": path}
            elif path and os.path.isfile(path) and path.lower().endswith((".exe", ".lnk", ".bat", ".cmd")):
                title, entry = "Programs", {"name": winsys.exe_name(path), "exe": path}
            elif re.match(r"^(https?://|www\.)\S+$", thing, re.I) or (
                    paste and current == "Links" and re.match(r"^[\w-]+(\.[\w-]+)+(/\S*)?$", thing)):
                url = thing if thing.lower().startswith("http") else "https://" + thing
                host = QtCore.QUrl(url).host().removeprefix("www.")
                title, entry = "Links", {"name": host or url, "url": url,
                                         "browser": store.get("last_browser") or ""}
            else:
                continue
            kind = KINDS[title]
            items = store.get(kind)
            if any(x.get("path") == entry.get("path", 0) or x.get("exe") == entry.get("exe", 0)
                   or x.get("url") == entry.get("url", 0) for x in items):
                continue                                   # already there
            entry["id"] = store.new_id()
            if self.chips.current:
                entry["tags"] = [self.chips.current]
            items.append(entry)
            store.put(kind, items)
            added[title] = added.get(title, 0) + 1
        if not added:
            if paste:
                self.app.toast("Nothing to add: copy a link, a folder or a program")
            return
        self.refresh()
        title = current if current in added else next(iter(added))
        self.tabs.setCurrentIndex([self.tabs.tabText(i) for i in range(self.tabs.count())].index(title))
        lst = self.lists[title]
        lst.setCurrentItem(lst.item(lst.count() - 1))
        self.app.toast("Added: " + ", ".join(f"{n} to {t}" for t, n in added.items()))

    def _toggle_view(self, title) -> None:
        views = dict(store.get("views") or {})
        views[title] = "list" if views.get(title) == "tiles" else "tiles"
        store.put("views", views)
        self._apply_view(title)

    def _apply_view(self, title) -> None:
        """Each tab keeps its own look: a list, or tiles with the name under the icon."""
        lst = self.lists[title]
        tiles = (store.get("views") or {}).get(title) == "tiles"
        if tiles:
            lst.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
            lst.setGridSize(RowDelegate.TILE + QtCore.QSize(4, 4))
            lst.setWrapping(True)
            lst.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        else:
            lst.setViewMode(QtWidgets.QListView.ViewMode.ListMode)
            lst.setGridSize(QtCore.QSize())
            lst.setWrapping(False)
        lst.setMovement(QtWidgets.QListView.Movement.Static)      # a drag reorders (Snap would only park it)
        lst.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DropOnly)   # rows move by _drag_rows
        lst.doItemsLayout()

    def _open_with(self, entry, browser) -> None:
        """This link opens in this browser (a profile = its own browser entry) - now and from now on."""
        if browser is None:
            browser = add_browser(self)
            if browser is None:
                return
        self._set("Links", entry, browser=browser)
        winsys.open_url(entry["url"], browser)

    def _fold(self, title, item) -> None:
        entry = self._find(title, item)
        if entry is not None and entry.get("folder"):
            entry["open"] = not entry.get("open", True)
            store.save()
            self.refresh()

    def new_group(self, title) -> None:
        items = store.get(KINDS[title])
        items.insert(0, {"id": store.new_id(), "title" if title == "Notes" else "name": "New Folder",
                         "folder": True, "open": True})
        store.put(KINDS[title], items)
        self.refresh()
        lst = self.lists[title]
        item = lst.item(0)
        if item is not None:                               # named in place
            lst.setCurrentItem(item)
            lst.editItem(item)

    def _run(self, entry) -> None:
        exe = entry.get("exe", "")
        if not os.path.exists(exe):
            self.app.toast(f"Not found: {exe}")
            return
        args = entry.get("args") or ""
        if args:
            import shlex
            subprocess.Popen([exe] + shlex.split(args.replace("\\", "/")), cwd=os.path.dirname(exe))  # noqa: S603
        else:
            os.startfile(exe)                                        # noqa: S606 - .lnk / .bat / .exe alike

    def _add(self, title) -> None:
        kind = KINDS[title]
        if title == "Notes":
            self.app.new_note()
            return
        if title == "Links":
            self._edit_link(None)
            return
        items = store.get(kind)
        if title == "Folders":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Add a folder")
            if not path:
                return
            path = os.path.normpath(path)
            entry = {"id": store.new_id(), "name": os.path.basename(path) or path, "path": path}
        else:
            path = self._pick_running()                    # a running program: no hunting for its folder
            if path is None:
                path, _f = QtWidgets.QFileDialog.getOpenFileName(
                    self, "Add a program", os.environ.get("PROGRAMFILES", "C:\\"),
                    "Programs (*.exe *.lnk *.bat *.cmd);;All files (*.*)")
            if not path:
                return
            path = os.path.normpath(path)
            entry = {"id": store.new_id(), "name": winsys.exe_name(path), "exe": path}
        if self.chips.current:
            entry["tags"] = [self.chips.current]          # added while a filter is on: it belongs there
        if getattr(self, "_into", ""):
            entry["parent"] = self._into
        items.append(entry)
        store.put(kind, items)
        self.refresh()
        lst = self.lists[title]
        item = lst.item(lst.count() - 1)
        if item is not None:                               # a new item is named in place
            lst.setCurrentItem(item)
            lst.editItem(item)

    def _pick_running(self):
        """A menu of the programs open right now: a click takes its .exe.
        Returns the path, "" when closed, None for Browse."""
        menu = QtWidgets.QMenu(self)
        have = {os.path.normcase(x.get("exe", "")) for x in store.get("programs")}
        for exe, title in winsys.running_apps():
            if os.path.normcase(exe) in have:
                continue
            a = menu.addAction(QtWidgets.QFileIconProvider().icon(QtCore.QFileInfo(exe)), winsys.exe_name(exe))
            a.setToolTip(exe)
            a.setData(exe)
        if menu.actions():
            menu.addSeparator()
        browse = menu.addAction(theme.icon("folder-open"), "Browse...")
        menu.setToolTipsVisible(True)
        got = menu.exec(QtGui.QCursor.pos())
        if got is None:
            return ""
        return None if got is browse else got.data()

    def _renamed(self, title, item) -> None:
        entry = self._find(title, item)
        text = item.text().strip()
        if entry is None or not text:
            return
        key = "title" if title == "Notes" else "name"
        if entry.get(key) != text:
            entry[key] = text
            store.save()

    def _edit_link(self, entry) -> None:
        dialog = LinkDialog(self, entry)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        links = store.get("links")
        if entry is not None:
            entry.update(dialog.value())
        else:
            new = dict(dialog.value(), id=store.new_id())
            if getattr(self, "_into", ""):
                new["parent"] = self._into
            if self.chips.current:
                new["tags"] = [self.chips.current]
            links.append(new)
        store.put("links", links)
        self.refresh()

    def _add_into(self, title, gid) -> None:
        if title == "Notes":
            self.app.new_note(gid)
            return
        self._into = gid
        try:
            self._add(title)
        finally:
            self._into = ""

    def _edit(self, title, item) -> None:
        entry = self._find(title, item)
        if entry is None:
            return
        if entry.get("folder"):
            self.lists[title].editItem(item)
            return
        if title == "Links":
            self._edit_link(entry)
        elif title == "Notes" and not entry.get("folder"):
            self.app.open_note(entry["id"])
        elif title == "Programs":
            dialog = ProgramDialog(self, entry)
            if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                entry.update(dialog.value())
                store.save()
                self.refresh()
        else:
            self.lists[title].editItem(item)

    def _delete(self, title, item) -> None:
        entry = self._find(title, item)
        if entry is None:
            return
        rest = [x for x in store.get(KINDS[title]) if x["id"] != entry["id"]]
        for x in rest:
            if x.get("parent") == entry["id"]:
                x.pop("parent")
        store.put(KINDS[title], rest)
        self.refresh()

    def _reordered(self, title, lst, row: int = -1) -> None:
        """Dragged into a new order - with a filter on, only the shown ones
        swap places among themselves. A note dropped under a folder (or
        among its notes) goes into it; under a loose note, out of it."""
        items = store.get(KINDS[title])
        if not self.chips.current and 0 <= row:
            moved = lst.item(min(row, lst.count() - 1))
            by_id = {x["id"]: x for x in items}
            got = by_id.get(moved.data(ROLE)) if moved is not None else None
            if got is not None and not got.get("folder"):
                i = lst.row(moved)
                above = by_id.get(lst.item(i - 1).data(ROLE)) if i > 0 else None
                parent = (above["id"] if above and above.get("folder") else (above or {}).get("parent"))
                if parent:
                    got["parent"] = parent
                else:
                    got.pop("parent", None)
            order = []
            for i in range(lst.count()):
                x = by_id.get(lst.item(i).data(ROLE))
                if x is None or x in order:
                    continue
                order.append(x)
                if x.get("folder") and not x.get("open", True):   # its hidden notes stay with it
                    order += [c for c in items if c.get("parent") == x["id"] and c not in order]
            order += [x for x in items if x not in order]
            store.put(KINDS[title], order)
            QtCore.QTimer.singleShot(0, self.refresh)
            return
        shown = [lst.item(i).data(ROLE) for i in range(lst.count())]
        slots = [i for i, x in enumerate(items) if x["id"] in shown]
        by_id = {x["id"]: x for x in items}
        for slot, hid in zip(slots, shown):
            items[slot] = by_id[hid]
        store.put(KINDS[title], items)

    def _set_all(self, title, entries, **kw) -> None:
        for e in entries:
            e.update(kw)
        store.save()
        self.refresh()

    def _tag_all(self, title, entries, fid, on) -> None:
        for e in entries:
            tags = list(e.get("tags") or [])
            if on and fid not in tags:
                tags.append(fid)
            elif not on and fid in tags:
                tags.remove(fid)
            e["tags"] = tags
        store.save()
        self.refresh()

    def _delete_all(self, title, entries) -> None:
        gone = {e["id"] for e in entries}
        rest = [x for x in store.get(KINDS[title]) if x["id"] not in gone]
        for x in rest:
            if x.get("parent") in gone:
                x.pop("parent")
        store.put(KINDS[title], rest)
        self.refresh()

    def _set(self, title, entry, **kw) -> None:
        entry.update(kw)
        store.save()
        self.refresh()

    def _menu(self, title, lst, pos) -> None:
        item = lst.itemAt(pos)
        entry = self._find(title, item)
        if item is not None and item.isSelected() and len(lst.selectedItems()) > 1:   # several picked: all of them
            targets = [x for x in (self._find(title, i) for i in lst.selectedItems()) if x is not None]
        else:
            if item is not None:
                lst.setCurrentItem(item)
            targets = [entry] if entry is not None else []
        many = len(targets) > 1
        menu = QtWidgets.QMenu(self)
        if entry is not None:
            group = bool(entry.get("folder"))
            if not group:
                menu.addAction(theme.icon("folder-open" if title == "Folders" else "globe" if title == "Links"
                                          else "rocket-launch" if title == "Programs" else "note-pencil"),
                               "Open", lambda: self._open(title, item))
            if title == "Links" and not group:
                sub = menu.addMenu(theme.icon("globe"), "Open With")     # opens AND remembers
                exes = {b["id"]: b.get("exe", "") for b in store.get("browsers")}
                for key, label in winsys.browsers():
                    exe = exes.get(key, "")
                    a = sub.addAction(QtWidgets.QFileIconProvider().icon(QtCore.QFileInfo(exe)) if os.path.isfile(exe)
                                      else theme.icon("globe"), label, lambda k=key: self._open_with(entry, k))
                    a.setCheckable(True)
                    a.setChecked((entry.get("browser") or "") == key)
                sub.addSeparator()
                sub.addAction(theme.icon("plus"), "Add Browser...", lambda: self._open_with(entry, None))
                menu.addAction(theme.icon("copy"), "Copy Link",
                               lambda: QtWidgets.QApplication.clipboard().setText(entry["url"]))
            if title in ("Folders", "Programs") and not group:
                path = entry.get("path") or entry.get("exe", "")
                menu.addAction(theme.icon("copy"), "Copy Path", lambda: QtWidgets.QApplication.clipboard().setText(path))
            if title == "Programs" and not group:
                menu.addAction(theme.icon("folder-open"), "Show in Explorer",
                               lambda: subprocess.Popen(["explorer", "/select,", entry["exe"]]))   # noqa: S603, S607
            menu.addAction(theme.icon("pencil-simple"), "Rename  (F2)", lambda: self.lists[title].editItem(item))
            if title in ("Links", "Programs") and not group:
                menu.addAction(theme.icon("gear"), "Edit...", lambda: self._edit(title, item))
            menu.addSeparator()
            # colour label
            colors = menu.addMenu(theme.icon("palette"), "Colour")
            none = colors.addAction("None", lambda: self._set_all(title, targets, color=""))
            none.setCheckable(True)
            none.setChecked(not entry.get("color"))
            for c in LABELS:
                swatch = QtGui.QPixmap(28, 28)
                swatch.fill(QtCore.Qt.GlobalColor.transparent)
                sp = QtGui.QPainter(swatch)
                sp.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
                sp.setBrush(QtGui.QColor(c))
                sp.setPen(QtCore.Qt.PenStyle.NoPen)
                sp.drawEllipse(4, 4, 20, 20)
                sp.end()
                action = colors.addAction(QtGui.QIcon(swatch), c.upper(), lambda c=c: self._set_all(title, targets, color=c))
                action.setCheckable(True)
                action.setChecked(entry.get("color") == c)
            # size
            sizes = menu.addMenu(theme.icon("frame-corners"), "Size")
            for key, name in (("l", "Large"), ("m", "Normal"), ("s", "Small")):
                action = sizes.addAction(name, lambda k=key: self._set_all(title, targets, size=k))
                action.setCheckable(True)
                action.setChecked((entry.get("size") or "m") == key)
            # filters
            tags = menu.addMenu(theme.icon("funnel"), "Filters")
            for f in filters():
                action = tags.addAction(f["name"])
                action.setCheckable(True)
                action.setChecked(f["id"] in (entry.get("tags") or []))
                action.toggled.connect(lambda on, fid=f["id"]: self._tag_all(title, targets, fid, on))
            if filters():
                tags.addSeparator()
            tags.addAction(theme.icon("plus"), "New Filter...", self.chips.new_filter)
            icons = menu.addMenu(theme.icon("image"), "Icon")      # every tab: folders, links, programs, notes
            for name in EMBLEMS:                                   # the library (on a folder: a glyph on its front)
                a = icons.addAction(QtGui.QIcon(theme.folder_pixmap(24, entry.get("color") or "", name))
                                    if title == "Folders" else theme.icon(name, 24, entry.get("color") or "#c9bba6"),
                                    name.replace("-", " ").title(),
                                    lambda n=name: self._set_all(title, targets, emblem=n, icon=""))
                a.setCheckable(True)
                a.setChecked(entry.get("emblem") == name and not entry.get("icon"))
            icons.addSeparator()
            icons.addAction(theme.icon("app-window"), "Windows Icons...", lambda: self._windows_icon(title, targets))
            icons.addAction(theme.icon("folder-open"), "From File...", lambda: self._pick_icon(title, targets))
            if entry.get("icon") or entry.get("emblem"):
                icons.addSeparator()
                icons.addAction(theme.icon("x"), "Reset Icon", lambda: self._set_all(title, targets, icon="", emblem=""))
            menu.addSeparator()
        if entry is not None and entry.get("folder"):
            menu.addAction(theme.icon("plus"), "New Note Here" if title == "Notes" else "Add Here",
                           lambda: self._add_into(title, entry["id"]))
        elif entry is not None:
            where = menu.addMenu(theme.icon("folder"), "Move to Folder")
            none = where.addAction("No Folder", lambda: self._set_all(title, targets, parent=""))
            none.setCheckable(True)
            none.setChecked(not entry.get("parent"))
            for f in store.get(KINDS[title]):
                if f.get("folder"):
                    a = where.addAction(QtGui.QIcon(theme.folder_pixmap(16, f.get("color") or "")),
                                        f.get("title") or f.get("name") or "Folder",
                                        lambda fid=f["id"]: self._set_all(title, targets, parent=fid))
                    a.setCheckable(True)
                    a.setChecked(entry.get("parent") == f["id"])
        menu.addAction(theme.icon("folder"), "New Folder", lambda: self.new_group(title))
        menu.addAction(theme.icon("plus"), f"Add to {title}", lambda: self._add(title))
        menu.addAction(theme.icon("funnel"), "New Filter...", self.chips.new_filter)
        if targets:                                     # last and red: easy to find, hard to hit by chance
            menu.addSeparator()
            menu.addAction(theme.icon("trash", 16, "#e5534b"), f"Delete {len(targets)} items" if many else "Delete",
                           lambda: self._delete_all(title, targets))
        menu.exec(lst.viewport().mapToGlobal(pos))

    def _tag(self, title, entry, fid, on) -> None:
        tags = list(entry.get("tags") or [])
        if on and fid not in tags:
            tags.append(fid)
        elif not on and fid in tags:
            tags.remove(fid)
        self._set(title, entry, tags=tags)

    def _windows_icon(self, title, entries) -> None:
        entries = entries if isinstance(entries, list) else [entries]
        old = entries[0].get("icon") or "" if entries else ""
        path, _, idx = old.rpartition("|") if "|" in old else (r"%SystemRoot%\System32\imageres.dll", "", "0")
        got = winsys.pick_icon(int(self.winId()), path, int(idx or 0))
        if got:
            self._set_all(title, entries, icon=got)

    def _pick_icon(self, title, entries) -> None:
        entries = entries if isinstance(entries, list) else [entries]
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            self, "Icon", os.path.expanduser("~"), "Images and icons (*.png *.jpg *.ico *.svg *.exe *.dll)")
        if path:
            self._set_all(title, entries, icon=os.path.normpath(path))

    def _history_menu(self, pos) -> None:
        item = self.history.itemAt(pos)
        if item is None:
            return
        hid = item.data(ROLE)
        path = os.path.join(store.history_dir(), hid + ".png")
        menu = QtWidgets.QMenu(self)
        menu.addAction(theme.icon("pencil-simple"), "Open and Draw", lambda: self.app.reopen(hid))
        menu.addAction(theme.icon("copy"), "Copy", lambda: QtWidgets.QApplication.clipboard().setImage(QtGui.QImage(path)))
        menu.addAction(theme.icon("push-pin"), "Pin to Screen", lambda: self.app.pin_file(path))
        menu.addAction(theme.icon("floppy-disk"), "Save Copy...", lambda: self._save_copy(path))
        menu.addAction(theme.icon("trash"), "Delete", lambda: self._delete_history(hid))
        menu.exec(self.history.viewport().mapToGlobal(pos))

    def _save_copy(self, path) -> None:
        name = datetime.datetime.now().strftime("LeadTool_%Y-%m-%d_%H-%M-%S.png")
        target, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save", os.path.join(store.save_dir(), name),
                                                           "PNG (*.png)")
        if target:
            QtGui.QImage(path).save(target)

    def _delete_history(self, hid) -> None:
        for suffix in (".png", "_base.png", ".json"):
            try:
                os.remove(os.path.join(store.history_dir(), hid + suffix))
            except OSError:
                pass
        store.put("history", [h for h in store.get("history") if h["id"] != hid])
        self.refresh_history()

    # ------------------------------------------------------------ window
    def _toggle_top(self) -> None:
        store.put("launcher_on_top", self.top_btn.isChecked())
        self._apply_top()
        self.show()

    def _apply_top(self) -> None:
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, bool(store.get("launcher_on_top")))

    def show_panel(self) -> None:
        self.refresh()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):                                     # noqa: N802
        """Closing the panel hides it - Lead Tool stays in the tray."""
        g = self.geometry()
        store.put("launcher_geometry", [g.x(), g.y(), g.width(), g.height()])
        e.ignore()
        self.hide()


class ProgramDialog(QtWidgets.QDialog):
    def __init__(self, parent, entry):
        super().__init__(parent)
        self.setWindowTitle("Program")
        self.setStyleSheet(theme.STYLE)
        form = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit(entry.get("name", ""))
        row = QtWidgets.QHBoxLayout()
        self.exe = QtWidgets.QLineEdit(entry.get("exe", ""))
        row.addWidget(self.exe, 1)
        browse = QtWidgets.QPushButton("...")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        self.args = QtWidgets.QLineEdit(entry.get("args", ""))
        self.args.setPlaceholderText("optional, e.g. a file to open")
        form.addRow("Name", self.name)
        form.addRow("Program", row)
        form.addRow("Arguments", self.args)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(480, 0)

    def _browse(self) -> None:
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Program", self.exe.text(),
                                                         "Programs (*.exe *.lnk *.bat *.cmd);;All files (*.*)")
        if path:
            self.exe.setText(os.path.normpath(path))

    def value(self) -> dict:
        exe = self.exe.text().strip()
        return {"name": self.name.text().strip() or os.path.splitext(os.path.basename(exe))[0], "exe": exe,
                "args": self.args.text().strip()}


class LinkDialog(QtWidgets.QDialog):
    def __init__(self, parent, entry=None):
        super().__init__(parent)
        self.setWindowTitle("Link")
        self.setStyleSheet(theme.STYLE)
        form = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit(entry["name"] if entry else "")
        self.url = QtWidgets.QLineEdit(entry["url"] if entry else "")
        clip = QtWidgets.QApplication.clipboard().text().strip()
        if not entry and clip.startswith(("http://", "https://")):
            self.url.setText(clip)                    # a link just copied comes in by itself
        self.browser = QtWidgets.QComboBox()
        self._fill(entry.get("browser", "") if entry else store.get("last_browser") or "")
        self.browser.activated.connect(self._picked)
        form.addRow("Name", self.name)
        form.addRow("URL", self.url)
        form.addRow("Open in", self.browser)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(480, 640)
        (self.name if self.url.text() else self.url).setFocus()

    def _fill(self, wanted: str) -> None:
        self.browser.clear()
        for key, label in winsys.browsers():
            self.browser.addItem(theme.icon("globe", 14), label, key)
        self.browser.addItem(theme.icon("plus", 14), "Add a browser...", "__add__")
        self.browser.setCurrentIndex(max(0, self.browser.findData(wanted)))

    def _picked(self, _i) -> None:
        if self.browser.currentData() == "__add__":
            bid = add_browser(self)
            self._fill(bid or "")

    def value(self) -> dict:
        url = self.url.text().strip()
        name = self.name.text().strip() or QtCore.QUrl(url if "://" in url else "https://" + url).host() or url
        browser = self.browser.currentData() or ""
        browser = "" if browser == "__add__" else browser
        store.data()["last_browser"] = browser
        return {"name": name, "url": url, "browser": browser}


class BrowserDialog(QtWidgets.QDialog):
    """One browser of yours: the program, a name, and (Chrome / Edge / Brave)
    which profile - added once, then every link just picks it. The profile is
    typed (its folder name, chrome://version > Profile Path): Lead Tool never
    reads the browser's own files."""

    def __init__(self, parent, entry=None):
        super().__init__(parent)
        self.setWindowTitle("Browser")
        self.setStyleSheet(theme.STYLE)
        form = QtWidgets.QFormLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.exe = QtWidgets.QLineEdit(entry["exe"] if entry else "")
        self.exe.setPlaceholderText(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        row.addWidget(self.exe, 1)
        browse = QtWidgets.QPushButton("...")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        form.addRow("Program", row)
        self.name = QtWidgets.QLineEdit(entry["name"] if entry else "")
        self.name.setPlaceholderText("Chrome - work profile")
        form.addRow("Name", self.name)
        self.profile = QtWidgets.QLineEdit()
        self.profile.setPlaceholderText("Default, Profile 2...")
        self.profile.textEdited.connect(self._profile_typed)
        form.addRow("Profile", self.profile)
        self.args = QtWidgets.QLineEdit(entry.get("args", "") if entry else "")
        self.args.setPlaceholderText('--profile-directory="Profile 2"')
        form.addRow("Arguments", self.args)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(520, 0)
        got = re.search(r'--profile-directory="?([^"]+)"?', self.args.text())
        self.profile.setText(got.group(1) if got else "")
        if not entry:
            QtCore.QTimer.singleShot(0, self._browse)

    def _browse(self) -> None:
        start = self.exe.text() or os.environ.get("PROGRAMFILES", "C:\\")
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Browser program", start, "Programs (*.exe)")
        if path:
            self.exe.setText(os.path.normpath(path))
            if not self.name.text().strip():
                self.name.setText(os.path.splitext(os.path.basename(path))[0].capitalize())

    def _profile_typed(self, text: str) -> None:
        text = text.strip()
        rest = re.sub(r'\s*--profile-directory=("[^"]*"|\S+)', "", self.args.text()).strip()
        self.args.setText(" ".join(x for x in (f'--profile-directory="{text}"' if text else "", rest) if x))

    def _ok(self) -> None:
        if not os.path.isfile(self.exe.text().strip()):
            self.exe.setFocus()
            self.exe.setStyleSheet("border: 1px solid #d9534f;")
            return
        self.accept()

    def value(self) -> dict:
        exe = self.exe.text().strip()
        return {"exe": exe, "name": self.name.text().strip() or os.path.basename(exe),
                "args": self.args.text().strip()}


def add_browser(parent, entry=None):
    """The editor; returns the browser's id (new or edited) or None."""
    dialog = BrowserDialog(parent, entry)
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return None
    items = store.get("browsers")
    if entry is not None:
        entry.update(dialog.value())
        bid = entry["id"]
    else:
        bid = store.new_id()
        items.append(dict(dialog.value(), id=bid))
    store.put("browsers", items)
    return bid


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, app):
        super().__init__(None)
        self.app = app
        from . import __version__
        self.setWindowTitle(f"Lead Tool {__version__} - Settings")
        self.setWindowIcon(theme.app_icon())
        self.setStyleSheet(theme.STYLE)
        form = QtWidgets.QFormLayout()        # goes on the "General" tab below
        self.keys = {}
        for key, label in (("capture", "Screenshot"), ("repeat", "Same area again"),
                           ("launcher", "Show panel"), ("note", "Quick note")):
            edit = QtWidgets.QKeySequenceEdit(QtGui.QKeySequence(store.get("hotkeys").get(key, "")))
            edit.setMaximumSequenceLength(1)
            self.keys[key] = edit
            form.addRow(label, edit)
        row = QtWidgets.QHBoxLayout()
        self.folder = QtWidgets.QLineEdit(store.save_dir())
        row.addWidget(self.folder, 1)
        browse = QtWidgets.QPushButton("...")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        form.addRow("Save folder", row)
        # YOUR BROWSERS: added once (program + profile), links pick them by name
        self.browsers = QtWidgets.QListWidget()
        self.browsers.setFixedHeight(96)
        self.browsers.itemDoubleClicked.connect(lambda _it: self._edit_browser())
        brow = QtWidgets.QVBoxLayout()
        brow.addWidget(self.browsers)
        bar = QtWidgets.QHBoxLayout()
        bar.addStretch(1)
        for icon, tip, slot in (("plus", "Add a browser", self._add_browser),
                                ("pencil-simple", "Edit", self._edit_browser),
                                ("trash", "Delete", self._delete_browser)):
            b = QtWidgets.QToolButton()
            b.setIcon(theme.icon(icon, 16))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
        brow.addLayout(bar)
        form.addRow("Browsers", brow)
        self._fill_browsers()
        self.autostart = QtWidgets.QCheckBox("Start with Windows")
        self.autostart.setChecked(bool(store.get("autostart")))
        form.addRow("", self.autostart)
        # the page above becomes "General"; "Keys" has every key of the editor
        general = QtWidgets.QWidget()
        general.setLayout(form)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(general, theme.icon("gear", 14), "General")
        tabs.addTab(self._keys_page(), theme.icon("keyboard", 14), "Keys")
        outer = QtWidgets.QVBoxLayout(self)
        outer.addWidget(tabs)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                             | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.resize(480, 640)

    _KEY_LABELS = (("select", "Cursor / move"), ("brush", "Brush"), ("eraser", "Eraser"), ("line", "Line"), ("arrow", "Arrow"),
                   ("rect", "Rectangle"), ("ellipse", "Ellipse"), ("text", "Text"), ("counter", "Number"),
                   ("blur", "Blur"), ("pixelate", "Pixelate"), ("callout", "Comment"), ("stamp", "Stamp"),
                   ("spotlight", "Spotlight"), ("magnify", "Magnify"), ("brushes", "Brush ring"), ("pie", "Pie menu"),
                   ("swap", "Swap colours"), ("picker", "Colour picker"), ("adjust", "Hold + drag: size / opacity"))

    def _keys_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        self.tool_keys = {}
        keys = store.get("keys")
        for key, label in self._KEY_LABELS:
            edit = QtWidgets.QKeySequenceEdit(QtGui.QKeySequence(keys.get(key, "")))
            edit.setMaximumSequenceLength(1)
            self.tool_keys[key] = edit
            form.addRow(label, edit)
        mouse = store.get("mouse")
        self.picker_button = QtWidgets.QComboBox()
        for value, text in (("middle", "Middle button"), ("right", "Right button"), ("", "Off")):
            self.picker_button.addItem(text, value)
        self.picker_button.setCurrentIndex(max(0, self.picker_button.findData(mouse.get("picker", "middle"))))
        form.addRow("Colour picker under the cursor", self.picker_button)
        self.mods = {}
        for key, label in (("eyedropper", "Click + this: pick a colour"), ("flow", "Drag + this: flow"),
                           ("move", "Click + this: move a mark")):
            combo = QtWidgets.QComboBox()
            for value in ("Alt", "Ctrl", "Shift", ""):
                combo.addItem(value or "Off", value)
            combo.setCurrentIndex(max(0, combo.findData(mouse.get(key, ""))))
            self.mods[key] = combo
            form.addRow(label, combo)
        # what the Tab pie shows - all ticked = everything
        from .overlay import TOOLS
        self.pie = QtWidgets.QListWidget()
        self.pie.setFixedHeight(150)
        chosen = set(store.get("pie_items") or [])
        for key, icon, name in list(TOOLS) + [("undo", "arrow-u-up-left", "Undo"), ("redo", "arrow-u-up-right", "Redo"),
                                              ("picker", "palette", "Colour"), ("paste", "clipboard-text", "Paste image"),
                                              ("pin", "push-pin", "Pin to screen"), ("ocr", "text-aa", "Copy text (OCR)"),
                                              ("save", "floppy-disk", "Save"), ("copy", "copy", "Copy")]:
            it = QtWidgets.QListWidgetItem(theme.icon(icon, 14), name)
            it.setData(ROLE, key)
            it.setFlags(it.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.CheckState.Checked if not chosen or key in chosen
                             else QtCore.Qt.CheckState.Unchecked)
            self.pie.addItem(it)
        form.addRow("Pie menu shows", self.pie)
        restore = QtWidgets.QPushButton("Restore defaults")
        restore.clicked.connect(self._restore_keys)
        form.addRow("", restore)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _restore_keys(self) -> None:
        defaults = store.DEFAULTS["keys"]
        for key, edit in self.tool_keys.items():
            edit.setKeySequence(QtGui.QKeySequence(defaults.get(key, "")))
        self.picker_button.setCurrentIndex(self.picker_button.findData(store.DEFAULTS["mouse"]["picker"]))
        for key, combo in self.mods.items():
            combo.setCurrentIndex(combo.findData(store.DEFAULTS["mouse"][key]))
        for i in range(self.pie.count()):
            self.pie.item(i).setCheckState(QtCore.Qt.CheckState.Checked)

    def _fill_browsers(self) -> None:
        self.browsers.clear()
        for b in store.get("browsers"):
            it = QtWidgets.QListWidgetItem(theme.icon("globe", 16, "#7fb2ff"), b["name"])
            it.setToolTip(f"{b['exe']}  {b.get('args', '')}")
            it.setData(ROLE, b["id"])
            self.browsers.addItem(it)

    def _add_browser(self) -> None:
        add_browser(self)
        self._fill_browsers()

    def _edit_browser(self) -> None:
        item = self.browsers.currentItem()
        entry = next((b for b in store.get("browsers") if item and b["id"] == item.data(ROLE)), None)
        if entry is not None:
            add_browser(self, entry)
            self._fill_browsers()

    def _delete_browser(self) -> None:
        item = self.browsers.currentItem()
        if item is not None:
            store.put("browsers", [b for b in store.get("browsers") if b["id"] != item.data(ROLE)])
            self._fill_browsers()

    def _browse(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Save folder", self.folder.text())
        if path:
            self.folder.setText(os.path.normpath(path))

    def _ok(self) -> None:
        hotkeys = store.get("hotkeys")
        for key, edit in self.keys.items():
            hotkeys[key] = edit.keySequence().toString(QtGui.QKeySequence.SequenceFormat.PortableText)
        keys = store.get("keys")
        for key, edit in self.tool_keys.items():
            keys[key] = edit.keySequence().toString(QtGui.QKeySequence.SequenceFormat.PortableText)
        mouse = store.get("mouse")
        mouse["picker"] = self.picker_button.currentData() or ""
        for key, combo in self.mods.items():
            mouse[key] = combo.currentData() or ""
        ticked = [self.pie.item(i).data(ROLE) for i in range(self.pie.count())
                  if self.pie.item(i).checkState() == QtCore.Qt.CheckState.Checked]
        store.data()["pie_items"] = [] if len(ticked) == self.pie.count() else ticked
        store.data()["save_dir"] = self.folder.text().strip()
        if bool(store.get("autostart")) != self.autostart.isChecked():
            winsys.set_autostart(self.autostart.isChecked())
            store.data()["autostart"] = self.autostart.isChecked()
        store.save()
        self.app.register_hotkeys()
        self.accept()

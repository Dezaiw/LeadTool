"""A quick note: pops up in the middle of the screen, you type, Ctrl+Enter
(or Esc) keeps it. Formatting like a word processor, kept small: Title,
Heading, Text, bold / italic / underline, bullets, a checklist, the font."""
import datetime

from PySide6 import QtCore, QtGui, QtWidgets

from . import store, theme
from .keys import latin

FONTS = ("Segoe UI", "Arial", "Calibri", "Georgia", "Consolas", "Comic Sans MS")
#: block styles: name -> (pixel size, bold)
STYLES = {"title": (24, True), "heading": (18, True), "text": (14, False)}


class NoteWindow(QtWidgets.QWidget):
    saved = QtCore.Signal()

    def __init__(self, note_id: str = ""):
        super().__init__(None, QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.WindowStaysOnTopHint
                         | QtCore.Qt.WindowType.Tool)
        self.setObjectName("ltNote")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.STYLE + f"#ltNote {{ background: #333333; border: 1px solid {theme.ACCENT};"
                                         " border-radius: 6px; }")
        self.note_id = note_id
        note = next((n for n in store.get("notes") if n["id"] == note_id), None)
        col = QtWidgets.QVBoxLayout(self)
        col.setContentsMargins(12, 10, 12, 10)
        head = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel()
        icon.setPixmap(theme.icon("note-pencil", 18, theme.ACCENT).pixmap(18, 18))
        head.addWidget(icon)
        self.title = QtWidgets.QLineEdit(note["title"] if note else "")
        self.title.setPlaceholderText("Title (optional)")
        head.addWidget(self.title, 1)
        col.addLayout(head)
        col.addLayout(self._toolbar())
        self.text = QtWidgets.QTextEdit()
        self.text.setAcceptRichText(True)
        font = QtGui.QFont("Segoe UI")
        font.setPixelSize(14)
        self.text.document().setDefaultFont(font)
        # the size lives in the style sheet: the app-wide 12 px one overrode the document font
        self.text.setStyleSheet("QTextEdit { background: #262626; font-size: 14px; font-family: 'Segoe UI'; }")
        if note and note.get("html"):
            self.text.setHtml(note["html"])
        elif note:
            self.text.setPlainText(note.get("text", ""))
        if not self.text.toPlainText():
            self.text.setPlaceholderText("Write it down...")
        self.text.cursorPositionChanged.connect(self._sync)
        self.text.viewport().installEventFilter(self)
        self.text.installEventFilter(self)
        col.addWidget(self.text, 1)
        hint = QtWidgets.QLabel("Ctrl+Enter or Esc saves  ·  Ctrl+1/2/0 title/heading/text  ·  Ctrl+B/I/U  ·  "
                                "Ctrl+Delete drops it")
        hint.setProperty("role", "hint")
        col.addWidget(hint)
        self.resize(560, 400)
        screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or QtGui.QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.move(g.center() - QtCore.QPoint(self.width() // 2, self.height() // 2))
        self._drag = None
        self.show()
        self.raise_()
        self.activateWindow()
        self.text.setFocus()
        cursor = self.text.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        self.text.setTextCursor(cursor)

    # ------------------------------------------------------------ toolbar
    def _toolbar(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(2)
        self.buttons = {}
        for key, icon, tip, slot, checkable in (
                ("title", "text-h-one", "Title  (Ctrl+1)", lambda: self.set_style("title"), True),
                ("heading", "text-h-two", "Heading  (Ctrl+2)", lambda: self.set_style("heading"), True),
                ("text", "paragraph", "Text  (Ctrl+0)", lambda: self.set_style("text"), True),
                ("bold", "text-b", "Bold  (Ctrl+B)", self.toggle_bold, True),
                ("italic", "text-italic", "Italic  (Ctrl+I)", self.toggle_italic, True),
                ("underline", "text-underline", "Underline  (Ctrl+U)", self.toggle_underline, True),
                ("bullets", "list-bullets", "Bullet list", lambda: self.toggle_list(QtGui.QTextListFormat.Style.ListDisc), False),
                ("numbers", "list-numbers", "Numbered list 1, 2, 3",
                 lambda: self.toggle_list(QtGui.QTextListFormat.Style.ListDecimal), False),
                ("checks", "list-checks", "Checklist (click a box to tick it)", self.add_checklist, False)):
            b = QtWidgets.QToolButton()
            b.setIcon(theme.icon(icon, 16))
            b.setIconSize(QtCore.QSize(16, 16))
            b.setFixedSize(28, 28)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            row.addWidget(b)
            self.buttons[key] = b
            if key in ("text", "underline"):
                line = QtWidgets.QFrame()
                line.setFixedSize(1, 18)
                line.setStyleSheet("background: #4a4a4a;")
                row.addWidget(line)
        row.addStretch(1)
        self.font_combo = QtWidgets.QComboBox()
        for name in FONTS:
            self.font_combo.addItem(name)
            self.font_combo.setItemData(self.font_combo.count() - 1, QtGui.QFont(name), QtCore.Qt.ItemDataRole.FontRole)
        self.font_combo.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.font_combo.activated.connect(lambda _i: self._merge(font=self.font_combo.currentText()))
        row.addWidget(self.font_combo)
        return row

    def _merge(self, **kw) -> None:
        fmt = QtGui.QTextCharFormat()
        if "bold" in kw:
            fmt.setFontWeight(QtGui.QFont.Weight.Bold if kw["bold"] else QtGui.QFont.Weight.Normal)
        if "italic" in kw:
            fmt.setFontItalic(kw["italic"])
        if "underline" in kw:
            fmt.setFontUnderline(kw["underline"])
        if "font" in kw:
            fmt.setFontFamilies([kw["font"]])
        if "size" in kw:
            fmt.setFontPointSize(kw["size"] * 0.75)
        cursor = self.text.textCursor()
        if not cursor.hasSelection() and "size" in kw:
            cursor.select(QtGui.QTextCursor.SelectionType.BlockUnderCursor)
        cursor.mergeCharFormat(fmt)
        self.text.mergeCurrentCharFormat(fmt)
        self.text.setFocus()
        self._sync()

    def set_style(self, name: str) -> None:
        """Title / Heading / Text for the whole paragraph - and for what you
        type next: on an empty line the style is waiting for the first letter.
        The active heading pressed again goes back to Text."""
        level = {"title": 1, "heading": 2}.get(name, 0)
        cursor = self.text.textCursor()
        if level and cursor.blockFormat().headingLevel() == level:
            name, level = "text", 0
        size, bold = STYLES[name]
        fmt = QtGui.QTextCharFormat()
        fmt.setFontPointSize(size * 0.75)
        fmt.setFontWeight(QtGui.QFont.Weight.Bold if bold else QtGui.QFont.Weight.Normal)
        cursor.beginEditBlock()
        line = QtGui.QTextCursor(cursor.block())             # this paragraph only, never the one above
        line.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock, QtGui.QTextCursor.MoveMode.KeepAnchor)
        line.mergeCharFormat(fmt)
        cursor.mergeBlockCharFormat(fmt)                     # an empty line keeps it for the first letter
        block = QtGui.QTextBlockFormat()
        block.setHeadingLevel(level)
        block.setTopMargin(8 if level else 0)
        cursor.mergeBlockFormat(block)
        cursor.endEditBlock()
        self.text.setTextCursor(cursor)
        self.text.mergeCurrentCharFormat(fmt)
        self.text.setPlaceholderText("")
        self.text.setFocus()
        self._sync()

    def _enter(self) -> bool:
        """Enter at the end of a title / heading: the next line is Text again
        (as in Word)."""
        cursor = self.text.textCursor()
        if not cursor.blockFormat().headingLevel() or not cursor.atBlockEnd():
            return False
        block = QtGui.QTextBlockFormat()
        block.setHeadingLevel(0)
        size, _bold = STYLES["text"]
        fmt = QtGui.QTextCharFormat()
        fmt.setFontPointSize(size * 0.75)
        fmt.setFontWeight(QtGui.QFont.Weight.Normal)
        cursor.insertBlock(block, fmt)
        self.text.setTextCursor(cursor)
        self.text.setCurrentCharFormat(fmt)
        self._sync()
        return True

    def toggle_bold(self) -> None:
        self._merge(bold=self.text.fontWeight() < QtGui.QFont.Weight.Bold)

    def toggle_italic(self) -> None:
        self._merge(italic=not self.text.fontItalic())

    def toggle_underline(self) -> None:
        self._merge(underline=not self.text.fontUnderline())

    def toggle_list(self, style) -> None:
        self.text.setPlaceholderText("")
        cursor = self.text.textCursor()
        current = cursor.currentList()
        if current is not None and current.format().style() != style:
            fmt = current.format()                 # bullets <-> 1, 2, 3
            fmt.setStyle(style)
            current.setFormat(fmt)
        elif current is not None:
            block = cursor.blockFormat()
            current.remove(cursor.block())
            block.setIndent(0)
            cursor.setBlockFormat(block)
        else:
            cursor.createList(style)
        self.text.setFocus()

    def add_checklist(self) -> None:
        self.text.setPlaceholderText("")
        cursor = self.text.textCursor()
        block = cursor.blockFormat()
        state = QtGui.QTextBlockFormat.MarkerType.Unchecked
        if block.marker() != QtGui.QTextBlockFormat.MarkerType.NoMarker:
            state = QtGui.QTextBlockFormat.MarkerType.NoMarker
        elif cursor.currentList() is None:
            cursor.createList(QtGui.QTextListFormat.Style.ListDisc)
        block = cursor.blockFormat()
        block.setMarker(state)
        cursor.setBlockFormat(block)
        self.text.setFocus()

    def _sync(self) -> None:
        fmt = self.text.currentCharFormat()
        level = self.text.textCursor().blockFormat().headingLevel()
        self.buttons["title"].setChecked(level == 1)
        self.buttons["heading"].setChecked(level == 2)
        self.buttons["text"].setChecked(level == 0)
        self.buttons["bold"].setChecked(fmt.fontWeight() >= QtGui.QFont.Weight.Bold)
        self.buttons["italic"].setChecked(fmt.fontItalic())
        self.buttons["underline"].setChecked(fmt.fontUnderline())
        families = fmt.fontFamilies() or []
        family = families[0] if families else "Segoe UI"
        i = self.font_combo.findText(family)
        if i >= 0:
            self.font_combo.setCurrentIndex(i)

    def eventFilter(self, obj, e):                               # noqa: N802
        """A click on a checklist box ticks it; Enter after a heading goes back to Text."""
        if obj is self.text and e.type() == QtCore.QEvent.Type.KeyPress and not e.modifiers()                 and e.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter) and self._enter():
            return True
        if obj is self.text.viewport() and e.type() == QtCore.QEvent.Type.MouseButtonPress:
            pos = e.position().toPoint()
            cursor = self.text.cursorForPosition(pos)
            block = cursor.block()
            fmt = block.blockFormat()
            if fmt.marker() != QtGui.QTextBlockFormat.MarkerType.NoMarker:
                rect = self.text.document().documentLayout().blockBoundingRect(block)
                left = rect.x() - self.text.horizontalScrollBar().value()
                if pos.x() < left + 6 and cursor.positionInBlock() == 0:
                    done = fmt.marker() == QtGui.QTextBlockFormat.MarkerType.Checked
                    fmt.setMarker(QtGui.QTextBlockFormat.MarkerType.Unchecked if done
                                  else QtGui.QTextBlockFormat.MarkerType.Checked)
                    QtGui.QTextCursor(block).setBlockFormat(fmt)
                    return True
        return super().eventFilter(obj, e)

    # ------------------------------------------------------------ keys / mouse
    def keyPressEvent(self, e):                                  # noqa: N802
        ctrl = e.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
        key = latin(e)
        if key == QtCore.Qt.Key.Key_Escape or (ctrl and key in (QtCore.Qt.Key.Key_Return,
                                                                QtCore.Qt.Key.Key_Enter, QtCore.Qt.Key.Key_S)):
            self.save_and_close()
        elif ctrl and key == QtCore.Qt.Key.Key_Delete:
            store.put("notes", [n for n in store.get("notes") if n["id"] != self.note_id])
            self.saved.emit()
            self.close()
        elif ctrl and key in (QtCore.Qt.Key.Key_1, QtCore.Qt.Key.Key_2, QtCore.Qt.Key.Key_0):
            self.set_style({QtCore.Qt.Key.Key_1: "title", QtCore.Qt.Key.Key_2: "heading"}.get(key, "text"))
        elif ctrl and key == QtCore.Qt.Key.Key_B:
            self.toggle_bold()
        elif ctrl and key == QtCore.Qt.Key.Key_I:
            self.toggle_italic()
        elif ctrl and key == QtCore.Qt.Key.Key_U:
            self.toggle_underline()
        else:
            super().keyPressEvent(e)

    def event(self, e):                                          # noqa: A003
        # the text box would take Ctrl+B / I / U / 1 / 2 / 0 itself - ours first
        if e.type() == QtCore.QEvent.Type.ShortcutOverride and e.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier \
                and latin(e) in (QtCore.Qt.Key.Key_B, QtCore.Qt.Key.Key_I, QtCore.Qt.Key.Key_U, QtCore.Qt.Key.Key_1,
                                QtCore.Qt.Key.Key_2, QtCore.Qt.Key.Key_0, QtCore.Qt.Key.Key_S):
            e.accept()
            return True
        return super().event(e)

    def save_and_close(self) -> None:
        plain, title = self.text.toPlainText().rstrip(), self.title.text().strip()
        if plain or title:
            now = datetime.datetime.now().isoformat(timespec="minutes")
            notes = store.get("notes")
            note = next((n for n in notes if n["id"] == self.note_id), None)
            if note is None:
                note = {"id": store.new_id(), "created": now}
                if getattr(self, "parent_folder", ""):          # made from a folder's menu: it lives there
                    note["parent"] = self.parent_folder
                notes.insert(0, note)
            note.update(title=title, text=plain, html=self.text.toHtml(), updated=now)
            store.put("notes", notes)
            self.saved.emit()
        self.close()

    # the window has no title bar: drag it by its edge
    def mousePressEvent(self, e):                                # noqa: N802
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):                                 # noqa: N802
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):                             # noqa: N802
        self._drag = None

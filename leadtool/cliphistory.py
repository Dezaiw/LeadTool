"""Clipboard history: every text / picture copied while Lead Tool runs, newest
first - one click puts it back on the clipboard. Memory only, gone on exit
(nothing copied is written to disk); what a password manager marks as
private is never taken - the same rule as Windows' own Win+V history."""
from PySide6 import QtCore, QtGui, QtWidgets

from . import store, theme

MAX_TEXT, MAX_IMAGES, MAX_LEN = 40, 12, 20000
# the formats password managers put next to a password (Windows clipboard history skips these too)
_PRIVATE = ("ExcludeClipboardContentFromMonitorProcessing", "Clipboard Viewer Ignore")


def private(mime) -> bool:
    formats = " ".join(mime.formats())
    if any(name in formats for name in _PRIVATE):
        return True
    for f in mime.formats():
        if "CanIncludeInClipboardHistory" in f or "CanUploadToCloudClipboard" in f:
            if bytes(mime.data(f))[:4] == b"\0\0\0\0":       # DWORD 0 = keep it out of any history
                return True
    return False


class ClipHistory(QtCore.QObject):
    def __init__(self, qapp):
        super().__init__()
        self.images = []                    # [(QImage, time)] this session
        self.texts = []                     # [{text, time}] this session
        if store.get("clip_history"):       # what older versions saved to disk: gone
            store.data().pop("clip_history", None)
            store.save()
        self._own = False                   # our own "put it back" is not a new entry
        qapp.clipboard().dataChanged.connect(self._changed)

    def _changed(self) -> None:
        if self._own:
            self._own = False
            return
        mime = QtWidgets.QApplication.clipboard().mimeData()
        now = QtCore.QDateTime.currentDateTime().toString("HH:mm")
        if mime is None or private(mime):
            return
        if mime.hasImage():
            image = QtGui.QImage(mime.imageData())
            if not image.isNull():
                self.images.insert(0, (image, now))
                del self.images[MAX_IMAGES:]
            return
        if mime.hasText():
            text = mime.text()
            if not text.strip() or len(text) > MAX_LEN:
                return
            self.texts = [t for t in self.texts if t["text"] != text]
            self.texts.insert(0, {"text": text, "time": now})
            del self.texts[MAX_TEXT:]

    def put_back(self, entry) -> None:
        self._own = True
        cb = QtWidgets.QApplication.clipboard()
        if isinstance(entry, QtGui.QImage):
            cb.setImage(entry)
        else:
            cb.setText(entry)

    def menu(self, parent) -> QtWidgets.QMenu:
        """The list: pictures (small) then texts, newest first."""
        menu = QtWidgets.QMenu(parent)
        menu.setStyleSheet(theme.STYLE + "QMenu { icon-size: 36px; }")   # pictures big enough to tell apart
        menu.setToolTipsVisible(True)
        for image, when in self.images:
            thumb = QtGui.QPixmap.fromImage(image.scaled(96, 54, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                                         QtCore.Qt.TransformationMode.SmoothTransformation))
            a = menu.addAction(QtGui.QIcon(thumb), f"Picture  {image.width()}×{image.height()}   {when}")
            a.triggered.connect(lambda _c=False, im=image: self.put_back(im))
        if self.images:
            menu.addSeparator()
        texts = self.texts
        for t in texts:
            line = " ".join(t["text"].split())
            a = menu.addAction((line[:70] + "…" if len(line) > 70 else line) + f"   {t.get('time', '')}")
            a.setToolTip(t["text"][:600])
            a.triggered.connect(lambda _c=False, tx=t["text"]: self.put_back(tx))
        if not self.images and not texts:
            empty = menu.addAction("Nothing copied yet")
            empty.setEnabled(False)
        else:
            menu.addSeparator()
            menu.addAction("Clear History", self.clear)
        return menu

    def clear(self) -> None:
        self.images = []
        self.texts = []

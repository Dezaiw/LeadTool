"""Lead Tool: lives in the tray, a hotkey away from a screenshot you can draw
on at once, your folders, your links and a quick note."""
import json
import os
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from . import capture, store, theme, winsys



class Toast(QtWidgets.QWidget):
    """A short message right at the cursor - you see at once that it was
    copied / saved. Click it to show the file in Explorer."""

    def __init__(self, text: str, path: str = ""):
        super().__init__(None, QtCore.Qt.WindowType.ToolTip | QtCore.Qt.WindowType.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("ltToast")
        self.setStyleSheet(f"#ltToast {{ background: #2b2b2b; border: 1px solid {theme.ACCENT}; border-radius: 8px; }}"
                           " QLabel { color: #f0f0f0; font: 13px 'Segoe UI'; }")
        self.path = path
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 9, 14, 9)
        icon = QtWidgets.QLabel()
        icon.setPixmap(theme.icon("check-circle", 20, "#57ab5a").pixmap(20, 20))
        row.addWidget(icon)
        row.addWidget(QtWidgets.QLabel(text))
        self.adjustSize()
        at = QtGui.QCursor.pos() + QtCore.QPoint(18, 18)
        g = (QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or QtGui.QGuiApplication.primaryScreen()).availableGeometry()
        self.move(min(at.x(), g.right() - self.width() - 8), min(at.y(), g.bottom() - self.height() - 8))
        self.show()
        QtCore.QTimer.singleShot(1800, self.close)

    def mousePressEvent(self, _e):                               # noqa: N802
        if self.path:
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.path)])   # noqa: S603, S607
        self.close()


class LeadTool(QtCore.QObject):
    def __init__(self, qapp: QtWidgets.QApplication):
        super().__init__()
        self.qapp = qapp
        self.overlays = []          # one frozen screen each while choosing; the chosen one stays
        self._kept = []
        self.hotkeys = winsys.Hotkeys()
        qapp.installNativeEventFilter(self.hotkeys)
        from .cliphistory import ClipHistory
        self.clips = ClipHistory(qapp)          # before the launcher: its button reads it
        from .launcher import Launcher
        self.launcher = Launcher(self)
        self.tray = QtWidgets.QSystemTrayIcon(theme.app_icon(), qapp)
        from . import __version__
        self.tray.setToolTip(f"Lead Tool {__version__}")
        menu = QtWidgets.QMenu()
        menu.setStyleSheet(theme.STYLE)
        menu.addAction(theme.icon("crop"), "Screenshot", self.capture)
        menu.addAction(theme.icon("clock-counter-clockwise"), "Same Area Again", lambda: self.capture(repeat=True))
        menu.addAction(theme.icon("note-pencil"), "Quick Note", self.new_note)
        menu.addAction(theme.icon("presentation-chart"), "Create Report", self.open_report)
        menu.addAction(theme.icon("frame-corners"), "Show Panel", self.launcher.show_panel)
        menu.addAction(theme.icon("gear"), "Settings", self.settings)
        menu.addSeparator()
        menu.addAction(theme.icon("x"), "Quit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.show()
        self.register_hotkeys()

    # ------------------------------------------------------------ plumbing
    def register_hotkeys(self) -> None:
        self.hotkeys.clear()
        keys = store.get("hotkeys")
        failed = []
        for name, action in (("capture", self.capture), ("repeat", lambda: self.capture(repeat=True)),
                             ("launcher", self.launcher.show_panel), ("note", self.new_note)):
            if keys.get(name) and not self.hotkeys.register(keys[name], action):
                failed.append(f"{keys[name]}")
        if failed:
            self.toast("Hotkey taken by another program: " + ", ".join(failed))

    def _tray_clicked(self, reason) -> None:
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            self.launcher.show_panel()
        elif reason == QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick:
            self.capture()

    def toast(self, text: str, path: str = "") -> None:
        self.keep(Toast(text, path))

    def keep(self, widget) -> None:
        """Pins / toasts have no parent: hold them until they close."""
        self._kept.append(widget)
        widget.destroyed.connect(lambda *_a, w=widget: self._kept.remove(w) if w in self._kept else None)

    def quit(self) -> None:
        self.hotkeys.clear()
        store.save()
        self.qapp.quit()

    # ------------------------------------------------------------ capture
    def capture(self, repeat: bool = False, from_panel: bool = False) -> None:
        if self.overlays:                              # the hotkey again: a new frame;
            for o in list(self.overlays):              # what was drawn is kept in History, not lost
                try:
                    if o.state == "edit" and o.shapes and o.pick is None:
                        o._remember(o.compose())
                    o.close()
                except RuntimeError:
                    pass
            QtCore.QTimer.singleShot(150, lambda: self.capture(repeat))
            return
        panel_was_up = self.launcher.isVisible()
        if from_panel and panel_was_up:
            self.launcher.hide()
            QtCore.QTimer.singleShot(180, lambda: self._grab(repeat, panel_was_up))
            return
        self._grab(repeat, False)

    # ------------------------------------------------------------ reports
    def open_report(self, new: bool = False) -> None:
        """Create Report: the report on screen - as it was left, or a new one."""
        from .overlay import Overlay
        old = getattr(self, "report_overlay", None)
        if old is not None and not new:
            try:
                old.show()
                old.raise_()
                old.activateWindow()
                return
            except RuntimeError:                         # already gone
                pass
        if old is not None:
            try:
                old.report_keep = False
                old.close()
            except RuntimeError:
                pass
        if new:
            self.report_session = None
        screen = capture.screen_at_cursor()
        avail = screen.availableGeometry()
        dpr = screen.devicePixelRatio()
        # only the report itself floats over the screen: a see-through window as big as
        # the monitor, empty places click through to the windows under it
        geo = QtCore.QRect(avail)
        canvas = QtGui.QPixmap(int(geo.width() * dpr), int(geo.height() * dpr))
        canvas.fill(QtCore.Qt.GlobalColor.transparent)
        canvas.setDevicePixelRatio(dpr)
        self.launcher.hide()
        session = getattr(self, "report_session", None)
        overlay = Overlay(self, canvas, geo, (), None, None, group=[], report=dict(session["report"]) if session else {})
        overlay.setWindowIcon(theme.app_icon())
        overlay.report_setup()
        if session:
            overlay.restore_report(session)
        self.report_overlay = overlay

    def report_pill(self, report_overlay) -> None:
        from .report import ShotPill
        self.keep(ShotPill(self, report_overlay))

    def capture_for(self, callback, repeat: bool = False) -> None:
        """A capture whose chosen area goes to callback(QImage) (None = cancelled)."""
        if self.overlays:
            return
        self._grab(repeat, False, pick=callback)

    def _grab(self, repeat: bool, restore_panel: bool, pick=None) -> None:
        """Every monitor frozen at once; the one where the selection STARTS is
        the capture, the others come back to life. Same area
        again: just that monitor."""
        from .overlay import Overlay
        last = store.get("last_area")
        screens = QtGui.QGuiApplication.screens()
        if repeat and last:                     # the monitor the last area was on
            screens = [QtGui.QGuiApplication.screenAt(QtCore.QPoint(int(last[0] + last[2] / 2),
                                                                    int(last[1] + last[3] / 2)))
                       or capture.screen_at_cursor()]
        shots = [capture.grab_screen(screen) for screen in screens]      # all grabbed before any overlay shows
        rects = winsys.window_rects()
        for base, geo in shots:
            dpr = base.devicePixelRatio()
            phys = QtCore.QRect(int(geo.x() * dpr), int(geo.y() * dpr), int(geo.width() * dpr), int(geo.height() * dpr))
            windows = [r.intersected(phys) for r in rects if r.intersects(phys)]
            preset = QtCore.QRectF(last[0] - geo.x(), last[1] - geo.y(), last[2], last[3]) if repeat and last else None
            overlay = Overlay(self, base, geo, windows, preset, group=self.overlays, pick=pick)
            overlay.closed.connect(lambda o=overlay: self._overlay_closed(o, restore_panel))
            self.overlays.append(overlay)
        under = capture.screen_at_cursor().geometry()
        for overlay in self.overlays:              # the keyboard goes to the screen under the cursor
            if overlay.geometry() == under:
                overlay.activateWindow()
                overlay.setFocus()

    def _overlay_closed(self, overlay, restore_panel: bool) -> None:
        if overlay in self.overlays:
            self.overlays.remove(overlay)
        if self.overlays:
            return
        if overlay.pick is not None:                     # a report's capture, cancelled: back to the report
            overlay.pick(None)
            return
        self.launcher.refresh_history()
        if restore_panel:
            self.launcher.show_panel()

    def reopen(self, hid: str) -> None:
        """A screenshot from History back on screen, its marks still editable."""
        from .overlay import Overlay
        if self.overlays:
            return
        folder = store.history_dir()
        image = QtGui.QPixmap(os.path.join(folder, hid + "_base.png"))
        if image.isNull():
            image = QtGui.QPixmap(os.path.join(folder, hid + ".png"))
        try:
            with open(os.path.join(folder, hid + ".json"), encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, ValueError):
            meta = {"shapes": []}
        screen = capture.screen_at_cursor()
        geo = screen.geometry()
        dpr = screen.devicePixelRatio()
        canvas = QtGui.QPixmap(int(geo.width() * dpr), int(geo.height() * dpr))
        canvas.fill(QtGui.QColor("#1e1e1e"))
        canvas.setDevicePixelRatio(dpr)
        shot_dpr = float(meta.get("dpr") or dpr)        # the scale it was TAKEN at: the marks are in its units
        w, h = image.width() / shot_dpr, image.height() / shot_dpr
        sg = screen.geometry().translated(-geo.topLeft())
        x, y = sg.center().x() - w / 2, sg.center().y() - h / 2
        p = QtGui.QPainter(canvas)
        p.drawPixmap(QtCore.QRectF(x, y, w, h), image, QtCore.QRectF(image.rect()))
        p.end()
        self.launcher.hide()
        overlay = Overlay(self, canvas, geo, (), QtCore.QRectF(x, y, w, h), {"id": hid, "shapes": meta["shapes"]},
                          group=self.overlays)
        overlay.closed.connect(lambda: self._overlay_closed(overlay, True))
        self.overlays.append(overlay)

    def pin_file(self, path: str) -> None:
        from .pin import PinWindow
        self.keep(PinWindow(QtGui.QPixmap(path), QtGui.QCursor.pos()))

    # ------------------------------------------------------------ notes / settings
    def new_note(self, folder: str = "") -> None:
        self.open_note("", folder)

    def open_note(self, note_id: str, folder: str = "") -> None:
        from .notes import NoteWindow
        window = NoteWindow(note_id)
        window.parent_folder = folder
        window.saved.connect(self.launcher.refresh)
        self.keep(window)

    def settings(self) -> None:
        from .launcher import SettingsDialog
        SettingsDialog(self).exec()


def _selftest(qapp) -> int:
    """LeadTool.exe --selftest: can this PC capture, read text and own the
    hotkey? Writes selftest.txt beside the data and exits (for the work PC)."""
    import time
    from . import ocr
    lines = []
    t = time.time()
    base, geo = capture.grab_desktop()
    lines.append(f"capture: {base.width()}x{base.height()} in {int((time.time() - t) * 1000)} ms, "
                 f"black={base.toImage().pixelColor(base.width() // 2, base.height() // 2).name() == '#000000'}")
    t = time.time()
    text = ocr.recognize(base.copy(0, 0, min(900, base.width()), min(500, base.height())).toImage())
    lines.append(f"ocr: {len(text)} chars in {int((time.time() - t) * 1000)} ms")
    hk = winsys.Hotkeys()
    for name, seq in store.get("hotkeys").items():
        lines.append(f"hotkey {name} {seq}: {'ok' if hk.register(seq, lambda: None) else 'TAKEN'}")
    hk.clear()
    lines.append(f"windows: {len(winsys.window_rects())}")
    path = os.path.join(store.app_dir(), "selftest.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return 0


def main() -> int:
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationName("Lead Tool")
    qapp.setWindowIcon(theme.app_icon())
    qapp.setStyleSheet(theme.STYLE)
    if "--selftest" in sys.argv:
        return _selftest(qapp)
    # ONE Lead Tool: a lock file beside the data; a second start writes "show" into the request
    # file the running one watches (an update writes "quit") - plain files, nothing else
    lock = QtCore.QLockFile(os.path.join(store.app_dir(), "running.lock"))
    request = os.path.join(store.app_dir(), "request.txt")
    if not lock.tryLock(0):
        with open(request, "w", encoding="utf-8") as handle:
            handle.write("show")
        return 0
    open(request, "w", encoding="utf-8").close()
    tool = LeadTool(qapp)
    watcher = QtCore.QFileSystemWatcher([request])

    def _request(_path=None):
        try:
            with open(request, encoding="utf-8") as handle:
                word = handle.read().strip()
        except OSError:
            word = ""
        if word:
            open(request, "w", encoding="utf-8").close()
        if request not in watcher.files() and os.path.exists(request):
            watcher.addPath(request)                    # a file written anew drops out of the watch
        if word == "quit":
            tool.quit()
        elif word == "show":
            tool.launcher.show_panel()
    watcher.fileChanged.connect(_request)
    if "--capture" in sys.argv:
        QtCore.QTimer.singleShot(300, tool.capture)
    if "--minimized" not in sys.argv and not store.get("autostart"):
        tool.launcher.show_panel()
    return qapp.exec()

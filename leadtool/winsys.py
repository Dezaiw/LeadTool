"""Windows glue: global hotkeys (RegisterHotKey), visible window rectangles
(for click-to-select-a-window while capturing), autostart, opening things."""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys

from PySide6 import QtCore, QtGui

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
WM_HOTKEY = 0x0312
MOD = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000


def _vk(name: str) -> int:
    name = name.strip().lower()
    special = {"printscreen": 0x2C, "print": 0x2C, "prtsc": 0x2C, "space": 0x20, "tab": 0x09,
               "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pause": 0x13,
               "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
               ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC}
    if name in special:
        return special[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit():
        return 0x6F + int(name[1:])
    return 0


def parse(sequence: str):
    """'Ctrl+Shift+S' -> (modifiers, vk) or None."""
    mods, vk = 0, 0
    for part in [p for p in sequence.replace(" ", "").split("+") if p]:
        low = part.lower()
        if low in MOD:
            mods |= MOD[low]
        else:
            vk = _vk(part)
    return (mods, vk) if vk else None


class Hotkeys(QtCore.QAbstractNativeEventFilter):
    """Hotkeys that work in every application. WM_HOTKEY comes to the
    thread's message queue; Qt's dispatcher hands it to this filter."""

    def __init__(self):
        super().__init__()
        self._actions = {}
        self._next = 1

    def register(self, sequence: str, action) -> bool:
        parsed = parse(sequence or "")
        if parsed is None:
            return False
        hid = self._next
        self._next += 1
        if not user32.RegisterHotKey(None, hid, parsed[0] | MOD_NOREPEAT, parsed[1]):
            return False              # taken by another program
        self._actions[hid] = action
        return True

    def clear(self) -> None:
        for hid in list(self._actions):
            user32.UnregisterHotKey(None, hid)
        self._actions.clear()

    def nativeEventFilter(self, event_type, message):            # noqa: N802
        if event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
            msg = wt.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in self._actions:
                QtCore.QTimer.singleShot(0, self._actions[msg.wParam])
                return True, 0
        return False, 0


def window_rects(exclude=()) -> list:
    """Visible top-level windows, front to back, as QRect in physical pixels
    (DWM's real frame, without the invisible resize border)."""
    rects = []
    EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    cloaked = wt.DWORD()

    def on_window(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or hwnd in exclude:
            return True
        dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)        # DWMWA_CLOAKED
        if cloaked.value:
            return True
        rect = wt.RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w > 40 and h > 30:
            rects.append(QtCore.QRect(rect.left, rect.top, w, h))
        return True
    user32.EnumWindows(EnumProc(on_window), 0)
    return rects


def open_path(path: str) -> None:
    os.startfile(path)                                           # noqa: S606


def browsers() -> list:
    """[(key, label)] - what a link can open in: the system default, or one
    of the browsers YOU added in Settings (program + optional profile)."""
    from . import store
    return [("", "Default browser")] + [(b["id"], b["name"]) for b in store.get("browsers")]


def open_url(url: str, browser: str = "") -> None:
    import shlex
    from . import store
    if not url.lower().startswith(("http://", "https://", "file:", "mailto:")):
        url = "https://" + url
    entry = next((b for b in store.get("browsers") if b["id"] == browser), None)
    if entry is not None and os.path.isfile(entry.get("exe", "")):
        # --profile-directory="Profile 2" -> one argument, quotes gone
        extra = shlex.split((entry.get("args") or "").replace("\\", "/"))
        subprocess.Popen([entry["exe"]] + extra + [url])                    # noqa: S603
        return
    QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))


def set_autostart(on: bool) -> None:
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE)
    try:
        if on:
            exe = sys.executable if getattr(sys, "frozen", False) else \
                f'"{sys.executable.replace("python.exe", "pythonw.exe")}" -m leadtool'
            winreg.SetValueEx(key, "LeadTool", 0, winreg.REG_SZ, f'"{exe}"' if getattr(sys, "frozen", False) else exe)
        else:
            try:
                winreg.DeleteValue(key, "LeadTool")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def pick_icon(hwnd: int, path: str = r"%SystemRoot%\System32\imageres.dll", index: int = 0):
    """Windows' own "Change Icon" window (the one from a folder's
    Properties): returns "file|index" or "" when cancelled."""
    import ctypes
    from ctypes import wintypes
    buf = ctypes.create_unicode_buffer(os.path.expandvars(path), 1024)
    idx = ctypes.c_int(index)
    fn = ctypes.windll.shell32.PickIconDlg
    fn.argtypes = (wintypes.HWND, wintypes.LPWSTR, wintypes.UINT, ctypes.POINTER(ctypes.c_int))
    if not fn(hwnd, buf, 1024, ctypes.byref(idx)):
        return ""
    return f"{os.path.expandvars(buf.value)}|{idx.value}"


def file_icon(path: str, index: int, side: int = 64):
    """Icon number `index` inside an .ico / .exe / .dll, as a QImage (or None)."""
    import ctypes
    from ctypes import wintypes
    from PySide6 import QtGui
    hicon = wintypes.HICON()
    got = ctypes.windll.user32.PrivateExtractIconsW(path, index, side, side, ctypes.byref(hicon), None, 1, 0)
    if got != 1 or not hicon:
        return None
    try:
        return QtGui.QImage.fromHICON(hicon.value)
    finally:
        ctypes.windll.user32.DestroyIcon(hicon)


def running_apps() -> list:
    """[(exe path, window title)] of the programs with a window on screen
    (minimised too) - one per program, this app left out."""
    out, seen = [], set()
    EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    cloaked = wt.DWORD()
    kernel32 = ctypes.windll.kernel32
    me = os.path.normcase(sys.executable)

    def on_window(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):           # GW_OWNER: a dialog
            return True
        dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
        n = user32.GetWindowTextLengthW(hwnd)
        if cloaked.value or not n:
            return True
        title = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, title, n + 1)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)                     # QUERY_LIMITED_INFORMATION
        if not handle:
            return True
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wt.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                exe = buf.value
                key = os.path.normcase(exe)
                if key not in seen and key != me and not key.endswith(("\explorer.exe", "\textinputhost.exe",
                                                                        "\applicationframehost.exe")):
                    seen.add(key)
                    out.append((exe, title.value))
        finally:
            kernel32.CloseHandle(handle)
        return True
    user32.EnumWindows(EnumProc(on_window), 0)
    return out


def exe_name(path: str) -> str:
    """The program's own name ("Yandex Browser", not "browser") - its FileDescription."""
    fallback = os.path.splitext(os.path.basename(path))[0]
    try:
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return fallback
        data = ctypes.create_string_buffer(size)
        ver.GetFileVersionInfoW(path, 0, size, data)
        ptr, length = ctypes.c_void_p(), wt.UINT()
        if not ver.VerQueryValueW(data, "\VarFileInfo\Translation", ctypes.byref(ptr), ctypes.byref(length)) \
                or length.value < 4:
            return fallback
        lang, cp = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ushort * 2)).contents
        if ver.VerQueryValueW(data, f"\StringFileInfo\{lang:04x}{cp:04x}\FileDescription",
                              ctypes.byref(ptr), ctypes.byref(length)) and length.value > 1:
            return ctypes.wstring_at(ptr, length.value - 1).strip() or fallback
    except OSError:
        pass
    return fallback

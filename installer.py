"""LeadToolSetup.exe - puts Lead Tool in %LOCALAPPDATA%\\Programs\\LeadTool
(no admin), over any older version: the running one is asked to quit, the
files are replaced, Start menu + Desktop shortcuts, then it starts.
Settings, notes and history live in %APPDATA%\\LeadTool and are never touched.
--silent: no message at the end."""
import ctypes
import os
import shutil
import subprocess
import sys
import time
import zipfile

APP = "Lead Tool"
REQUEST = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "LeadTool", "request.txt")
TARGET = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", "LeadTool")


def _message(text: str, error: bool = False) -> None:
    if "--silent" not in sys.argv:
        ctypes.windll.user32.MessageBoxW(None, text, f"{APP} Setup", 0x10 if error else 0x40)


def _package() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "app.zip")


def _stop_running() -> None:
    """Ask a running Lead Tool to quit (the request file it watches) - never a forced kill."""
    try:
        with open(REQUEST, "w", encoding="utf-8") as handle:
            handle.write("quit")
    except OSError:
        pass                                # never started on this PC


def _shortcut(path: str, target: str) -> None:
    """A .lnk through Windows' own IShellLink (COM, no PowerShell)."""
    from ctypes import POINTER, WINFUNCTYPE, byref, c_void_p, c_wchar_p, oledll, windll
    from ctypes.wintypes import BOOL, DWORD

    class GUID(ctypes.Structure):
        _fields_ = [("a", DWORD), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]

    def guid(text: str) -> GUID:
        g = GUID()
        oledll.ole32.CLSIDFromString(c_wchar_p(text), byref(g))
        return g

    def call(obj, index, *types):
        vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        return WINFUNCTYPE(ctypes.HRESULT, c_void_p, *types)(vtable[index])

    windll.ole32.CoInitialize(None)
    link = c_void_p()
    oledll.ole32.CoCreateInstance(byref(guid("{00021401-0000-0000-C000-000000000046}")), None, 1,
                                  byref(guid("{000214F9-0000-0000-C000-000000000046}")), byref(link))
    try:
        call(link, 20, c_wchar_p)(link, target)                                   # SetPath
        call(link, 9, c_wchar_p)(link, os.path.dirname(target))                   # SetWorkingDirectory
        call(link, 17, c_wchar_p, ctypes.c_int)(link, target, 0)                  # SetIconLocation
        persist, iid = c_void_p(), guid("{0000010B-0000-0000-C000-000000000046}")
        call(link, 0, POINTER(GUID), POINTER(c_void_p))(link, byref(iid), byref(persist))   # IPersistFile
        try:
            call(persist, 6, c_wchar_p, BOOL)(persist, path, True)                # Save
        finally:
            call(persist, 2)(persist)
    finally:
        call(link, 2)(link)                                                       # Release


def main() -> int:
    package = _package()
    if not os.path.isfile(package):
        _message("The setup is damaged: app.zip missing.", True)
        return 1
    _stop_running()
    staging = TARGET + ".new"
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(package) as archive:
        archive.extractall(staging)
    inner = os.path.join(staging, "LeadTool")              # the zip holds the LeadTool folder
    source = inner if os.path.isdir(inner) else staging
    old = TARGET + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(TARGET):
        for attempt in range(30):           # a polite quit takes well under 3 s
            try:
                os.rename(TARGET, old)
                break
            except OSError:
                time.sleep(0.2)
        else:
            _message("Lead Tool is still running - close it from the tray and run the setup again.", True)
            shutil.rmtree(staging, ignore_errors=True)
            return 1
    shutil.move(source, TARGET)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    exe = os.path.join(TARGET, "LeadTool.exe")
    programs = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
    _shortcut(os.path.join(programs, f"{APP}.lnk"), exe)
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(desktop):
        _shortcut(os.path.join(desktop, f"{APP}.lnk"), exe)
    if "--no-launch" not in sys.argv:
        subprocess.Popen([exe], cwd=TARGET)                                   # noqa: S603
    _message(f"{APP} {_version()} installed.\n\n{TARGET}\n\nCtrl+Shift+S - screenshot. It lives in the tray.")
    return 0


def _version() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, "version.txt"), encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


if __name__ == "__main__":
    sys.exit(main())

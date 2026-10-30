"""Build the portable Lead Tool: dist/LeadTool/LeadTool.exe (a folder - copy
it anywhere, no install, no admin)."""
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(ROOT, "build", "app", "LeadTool")      # the app; dist/ gets the zip + LeadToolSetup.exe
# Qt parts Lead Tool never touches - the folder shrinks by most of its size
_UNUSED = ("QtQml", "QtQuick", "QtQuickWidgets", "QtQuick3D", "QtQuickControls2", "QtWebEngineCore",
           "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets", "QtMultimedia",
           "QtMultimediaWidgets", "QtCharts", "QtDataVisualization", "QtGraphs", "Qt3DCore", "Qt3DRender",
           "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "QtPdf", "QtPdfWidgets", "QtSql",
           "QtTest", "QtDesigner", "QtHelp", "QtBluetooth", "QtNfc", "QtSensors", "QtSerialPort",
           "QtSerialBus", "QtPositioning", "QtLocation", "QtRemoteObjects", "QtScxml", "QtSpatialAudio",
           "QtTextToSpeech", "QtHttpServer", "QtNetwork", "QtOpenGLWidgets", "QtUiTools", "QtConcurrent", "QtStateMachine")


def make_ico(path: str) -> None:
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    sys.path.insert(0, ROOT)
    from leadtool import theme
    theme.app_icon().pixmap(256, 256).save(path, "ICO")
    del app


def main() -> None:
    import py_compile
    for path in glob.glob(os.path.join(ROOT, "leadtool", "*.py")) + [os.path.join(ROOT, "installer.py")]:
        py_compile.compile(path, doraise=True)       # a broken module never reaches the installer
    ico = os.path.join(ROOT, "build", "leadtool.ico")
    os.makedirs(os.path.dirname(ico), exist_ok=True)
    make_ico(ico)
    sys.path.insert(0, ROOT)
    import installer
    installer._stop_running()          # a running Lead Tool from dist/ locks its exe   # noqa: SLF001
    info = version_file("LeadTool.exe", "Lead Tool - screenshots, notes and a launcher")
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--noupx",
        "--version-file", info,
        "--name", "LeadTool", "--icon", ico, "--distpath", os.path.join(ROOT, "build", "app"),
        "--workpath", os.path.join(ROOT, "build", "pyi"), "--specpath", os.path.join(ROOT, "build"),
        "--add-data", f"{os.path.join(ROOT, 'leadtool', 'icons')}{os.pathsep}icons",
        "--add-data", f"{os.path.join(ROOT, 'leadtool', 'brushes')}{os.pathsep}brushes",
        "--collect-submodules", "winrt",
        "--exclude-module", "tkinter",
        *[a for m in _UNUSED for a in ("--exclude-module", f"PySide6.{m}")],
        os.path.join(ROOT, "run_leadtool.py")], cwd=ROOT)
    prune(os.path.join(APP_DIR, "_internal", "PySide6"))
    print("built:", os.path.join(APP_DIR, "LeadTool.exe"))
    print("zip:", build_zip())
    setup = build_setup(ico)
    print("setup:", setup)
    if "--install" in sys.argv:                 # this PC: the new version in place right away
        subprocess.check_call([setup, "--silent"])


def build_setup(ico: str) -> str:
    """One LeadToolSetup.exe: the app folder zipped inside a small stdlib-only installer."""
    import zipfile
    sys.path.insert(0, ROOT)
    from leadtool import __version__
    work = os.path.join(ROOT, "build", "setup")
    os.makedirs(work, exist_ok=True)
    package = os.path.join(work, "app.zip")
    app_dir = APP_DIR
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for folder, _dirs, files in os.walk(app_dir):
            for name in files:
                path = os.path.join(folder, name)
                archive.write(path, os.path.join("LeadTool", os.path.relpath(path, app_dir)))
    with open(os.path.join(work, "version.txt"), "w", encoding="utf-8") as handle:
        handle.write(__version__)
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
        "--name", "LeadToolSetup", "--icon", ico, "--noupx",
        "--version-file", version_file("LeadToolSetup.exe", "Lead Tool Setup"), "--workpath", os.path.join(work, "pyi"),
        "--specpath", work, "--distpath", os.path.join(ROOT, "dist"),
        "--add-data", f"{package}{os.pathsep}.", "--add-data", f"{os.path.join(work, 'version.txt')}{os.pathsep}.",
        "--exclude-module", "PySide6", "--exclude-module", "tkinter",
        os.path.join(ROOT, "installer.py")], cwd=ROOT)
    return os.path.join(ROOT, "dist", "LeadToolSetup.exe")


def build_zip() -> str:
    """dist/LeadTool-<version>.zip - unpack anywhere and run LeadTool.exe, nothing installs
    (the setup-free way for a strict company PC)."""
    import zipfile
    sys.path.insert(0, ROOT)
    from leadtool import __version__
    path = os.path.join(ROOT, "dist", f"LeadTool-{__version__}.zip")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for old in glob.glob(os.path.join(ROOT, "dist", "LeadTool-*.zip")):
        os.remove(old)                                      # a build output, made again right below
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for folder, _dirs, files in os.walk(APP_DIR):
            for name in files:
                full = os.path.join(folder, name)
                archive.write(full, os.path.join("LeadTool", os.path.relpath(full, APP_DIR)))
    return path


def version_file(exe: str, description: str) -> str:
    """The Details tab of the exe (name, description, version): an exe without it looks suspicious."""
    sys.path.insert(0, ROOT)
    from leadtool import __version__
    nums = tuple(int(n) for n in __version__.split(".")) + (0,) * (4 - len(__version__.split(".")))
    path = os.path.join(ROOT, "build", f"version_{exe}.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pairs = {"CompanyName": "Lead Tool", "FileDescription": description, "FileVersion": __version__,
             "InternalName": exe[:-4], "OriginalFilename": exe, "ProductName": "Lead Tool",
             "ProductVersion": __version__, "LegalCopyright": "Lead Tool"}
    strings = ",\n".join(f"          StringStruct('{k}', '{v}')" for k, v in pairs.items())
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums[:4]}, prodvers={nums[:4]}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
{strings}])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""")
    return path


# DLLs the PySide6 hook ships anyway: QML / Quick / PDF / software OpenGL / translations
_DROP = ("Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6OpenGL.", "opengl32sw", "Qt6ShaderTools",
         "Qt6Multimedia", "Qt6WebSockets", "Qt6Network")


def prune(folder: str) -> None:
    import shutil
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if name == "translations" or name == "qml" or any(name.startswith(d) for d in _DROP):
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)


if __name__ == "__main__":
    main()

"""Everything Lead Tool remembers, in one JSON file.

Portable: a file named `portable` next to the exe keeps the data beside it;
otherwise %APPDATA%\\LeadTool.
"""
import copy
import glob
import json
import os
import sys
import uuid

DEFAULTS = {
    "hotkeys": {"capture": "Ctrl+Shift+S", "repeat": "Ctrl+Alt+S",
                "launcher": "Ctrl+Alt+L", "note": "Ctrl+Alt+N"},
    # every key / mouse button of the editor is the user's to change (Settings > Keys)
    "keys": {"select": "W", "brush": "P", "eraser": "X", "line": "L", "arrow": "A", "rect": "R", "ellipse": "E",
             "text": "T", "counter": "N", "blur": "B", "pixelate": "M",
             "callout": "K", "stamp": "S", "spotlight": "F", "magnify": "Z", "lasso": "O",
             "brushes": "Q", "pie": "Tab", "swap": "Shift+X", "picker": "C", "adjust": "Space"},
    # Ctrl + drag = flow (Painter's), Alt + click = eyedropper, middle button = palette
    # right button = palette, middle = the copy / save / paste menu
    "mouse": {"picker": "right", "eyedropper": "Alt", "move": "", "flow": "Ctrl"},
    "keys_version": 3,
    "stamp": "check-circle",
    "pie_items": [],        # empty = everything; else the ids shown in the Tab pie
    "brush": "basic_soft",
    "angle": 0.0,
    "save_dir": "",
    "launcher_on_top": False,
    "launcher_geometry": None,
    "autostart": False,
    "colors": ["#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#32ade6", "#007aff", "#af52de", "#ffffff", "#000000"],
    "color": "#ff3b30",
    "color2": "#ffffff",
    "width": 4,
    "opacity": 1.0,
    "font": "Segoe UI",
    "text_box": False,
    "last_area": None,
    "folders": [],          # {id, name, path}
    "links": [],            # {id, name, url, browser}  browser: "" = default, else a browsers id
    "browsers": [],         # {id, name, exe, args}  added by hand in Settings
    "programs": [],         # {id, name, exe, args}
    "filters": [],          # {id, name, match}  chips over every list
    "notes": [],            # {id, title, text, html, created, updated}
    # every list item may also carry: color (label), size s/m/l, icon (own file), tags [filter ids]
    "history": [],          # {id, file, base, shapes, created}
    "history_max": 60,
}

_data = None


def app_dir() -> str:
    exe_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(sys.argv[0]))
    if os.path.isfile(os.path.join(exe_dir, "portable")):
        path = os.path.join(exe_dir, "data")
    else:
        path = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "LeadTool")
    os.makedirs(path, exist_ok=True)
    return path


def _file() -> str:
    return os.path.join(app_dir(), "data.json")


def data() -> dict:
    global _data
    if _data is None:
        _data = copy.deepcopy(DEFAULTS)
        try:
            with open(_file(), encoding="utf-8") as handle:
                stored = json.load(handle)
            from . import __version__
            if stored.get("app_version") != __version__:      # a new version: keep a copy of what was there
                import shutil
                shutil.copy2(_file(), os.path.join(app_dir(), f"data.before-{__version__}.json"))
                stored["app_version"] = __version__
                olds = sorted(glob.glob(os.path.join(app_dir(), "data.before-*.json")), key=os.path.getmtime)
                for old in olds[:-3]:                   # the last three copies are enough
                    os.remove(old)
            if stored.get("keys_version", 1) < DEFAULTS["keys_version"]:
                # the editor's keys were re-planned (0.4): start from the new defaults once
                stored.pop("keys", None)
                stored.pop("mouse", None)
                stored["keys_version"] = DEFAULTS["keys_version"]
            for key, value in stored.items():
                if key in ("hotkeys", "keys", "mouse") and isinstance(value, dict):
                    _data[key].update(value)
                else:
                    _data[key] = value
        except (OSError, ValueError):
            pass
    return _data


def save() -> None:
    tmp = _file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data(), handle, ensure_ascii=False, indent=1)
    os.replace(tmp, _file())


def get(key):
    return data().get(key, DEFAULTS.get(key))


def put(key, value) -> None:
    data()[key] = value
    save()


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def save_dir() -> str:
    path = get("save_dir") or os.path.join(os.path.expanduser("~"), "Pictures", "LeadTool")
    os.makedirs(path, exist_ok=True)
    return path


def history_dir() -> str:
    path = os.path.join(app_dir(), "history")
    os.makedirs(path, exist_ok=True)
    return path

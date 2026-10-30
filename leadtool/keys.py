"""Hotkeys by the physical key, whatever the keyboard layout: on a Russian
layout Qt reports "Ц" for the W key, so every letter shortcut was dead.
Windows' virtual key code is the same on every layout."""
from PySide6 import QtCore


def latin(e) -> QtCore.Qt.Key:
    vk = e.nativeVirtualKey()
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:      # A-Z, 0-9: Qt's codes are the same numbers
        return QtCore.Qt.Key(vk)
    try:
        return QtCore.Qt.Key(e.key())
    except ValueError:                                 # a Cyrillic letter on a non-letter key ("х" on "[")
        return e.key()

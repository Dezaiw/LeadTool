# Lead Tool - security overview

Lead Tool is a small productivity utility for Windows that cuts routine tasks.

It was developed on a personal (non-work) computer with an AI coding assistant (Claude Code by
Anthropic). No AI or development tools are used on the work machine; only the finished app is.
It is not a commercial product and has no telemetry, accounts or updates from the internet.

What it does:
- a screenshot of one monitor with drawing on top (like Lightshot / ShareX);
- a report image: screenshots in a row with a task number, asset name and stage typed in by hand;
- a launcher panel: folders, links, programs and notes added by the user;
- a clipboard history.

It lives in the system tray.

## How it is built
- Python 3.10.11, all source code in `leadtool/` (~8k lines, plain Python, no obfuscation).
- Third-party packages (from PyPI, pinned in `requirements.txt`):
  PySide6 6.12.0 (Qt UI), numpy 2.2.6 (image filters), winrt 3.2.1 (Windows' built-in OCR),
  PyInstaller 6.22.3 (packaging only).
- `build.py` runs PyInstaller (one-folder build, no UPX) and produces:
  - `dist/LeadTool-<version>.zip` - unzip and run `LeadTool.exe`; nothing is installed;
  - `dist/LeadToolSetup.exe` - optional per-user installer (`installer.py`, standard library only):
    copies the folder to `%LOCALAPPDATA%\Programs\LeadTool`, creates Start menu / Desktop
    shortcuts through Windows' IShellLink COM interface. No admin rights, no services, no drivers.
- The binaries are not code-signed (no certificate). Rebuild from this source to compare.

To build: `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`, `.venv\Scripts\python build.py`.

## Network
None. The app has no network code: no HTTP requests, sockets, pipes, telemetry, update checks or cloud.
Qt's network module is excluded from the build (`build.py`).
Only one copy runs: a lock file (`%APPDATA%\LeadTool\running.lock`) plus a small request file
that a second start writes "show" into.
Links saved in the launcher are opened in the browser only when the user clicks them.

## Windows APIs used (all in `leadtool/winsys.py` unless noted)
| What | API | When |
|---|---|---|
| Global hotkeys | `RegisterHotKey` (standard, no keyboard hook, no key logging) | at start, keys chosen by the user |
| Screenshot | Qt `QScreen.grabWindow` (`capture.py`) | only when the user presses the capture hotkey |
| Window snapping while capturing | `EnumWindows`, `GetWindowRect`, `DwmGetWindowAttribute` | during a capture |
| "Add a running program" picker | `EnumWindows`, `OpenProcess(QUERY_LIMITED_INFORMATION)`, `QueryFullProcessImageNameW` - reads exe path and window title only | only when the user opens that picker |
| Program icons / names | `PickIconDlg`, `PrivateExtractIconsW`, `GetFileVersionInfo` | when the user adds a program |
| Autostart | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\LeadTool` | only if the user turns it on (off by default) |
| Text recognition | `Windows.Media.Ocr` (offline, built into Windows) | only when the user asks for OCR |
| Opening things | `os.startfile`, `subprocess.Popen` of programs/browsers the user added, `explorer /select` | on the user's click |

Not used: network access, keyboard/mouse hooks, PowerShell or other scripts, process injection or
memory access of other programs, admin rights, services, scheduled tasks, browser data/profiles/
cookies/passwords, registry outside the one autostart value, code downloaded or generated at run time.

## Clipboard
- The clipboard history keeps what the user copies **in memory only**; it is gone when the app exits.
- Items marked private by password managers (`ExcludeClipboardContentFromMonitorProcessing`,
  `CanIncludeInClipboardHistory = 0`) are skipped - the same rule as Windows' own clipboard history.

## Data on disk (all local, nothing leaves the PC)
- `%APPDATA%\LeadTool\data.json` - settings, links/folders/programs, notes, recent report
  fields (task/asset typed by hand); last 3 backups of it.
- `%APPDATA%\LeadTool\history\` - the last 60 screenshots the user took (PNG + drawing data).
- Screenshots / reports the user saves go to the folder the user chooses (default `Pictures\LeadTool`).

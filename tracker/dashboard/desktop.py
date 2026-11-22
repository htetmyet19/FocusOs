"""FocusOs as a Windows desktop app: the dashboard in its own window.

The Flask server from server.py runs on a background thread, bound to
127.0.0.1 only, and a native window (Edge WebView2 via pywebview) shows it,
with no browser, address bar or tabs. Closing the window ends the app. A
focus session that is running keeps going: the tracker is its own process.

    python desktop.py          (start.bat does this)
"""
from __future__ import annotations

import ctypes
import os
import socket
import sys
import threading
from pathlib import Path

APP_NAME = "FocusOs"
PREFERRED_PORT = 8765            # fixed, so the window's saved settings (theme, goal) survive restarts
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME

# Files bundled with the app (the icon): next to this file, or unpacked by PyInstaller.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ICON = BUNDLE_DIR / "focusos.ico"

# Packaged as an .exe (PyInstaller)? Then tracker/, ai/, db/ and pgsql/ sit next
# to the exe, not next to this file. Must be set before the other modules load.
if getattr(sys, "frozen", False):
    os.environ.setdefault("FOCUSOS_ROOT", str(Path(sys.executable).resolve().parent))

# No console (pythonw or the .exe): print() would fail, so log to a file instead.
if sys.stdout is None or sys.stderr is None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _log = open(DATA_DIR / "desktop.log", "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9


def message_box(text: str, error: bool = True) -> None:
    _user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)   # MB_ICONERROR / MB_ICONINFORMATION


def claim_single_instance():
    """A named mutex makes the app single-instance (the same OS idea the
    tracker uses). If FocusOs is already open, bring its window to the front."""
    import time
    for _ in range(50):                  # up to ~10 s (closing takes ~4 s after the window hides)
        handle = _kernel32.CreateMutexW(None, False, "Local\\FocusOs.Desktop")
        if _kernel32.GetLastError() != _ERROR_ALREADY_EXISTS:
            return handle                # keep a reference: the mutex lives as long as the process
        hwnd = _user32.FindWindowW(None, APP_NAME)
        if hwnd:                         # already open: show that window instead
            _user32.ShowWindow(hwnd, _SW_RESTORE)
            _user32.SetForegroundWindow(hwnd)
            sys.exit(0)
        # Lock held but no window: the previous copy is still closing. Wait for it.
        _kernel32.CloseHandle(handle)
        time.sleep(0.2)
    sys.exit(0)


def windows_uses_dark_mode() -> bool:
    """Windows' "app mode" setting, so the window opens in the right colour."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def pick_port() -> int:
    for port in (PREFERRED_PORT, 0):     # 0 = any free port if the preferred one is taken
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free local port")


def on_closed(httpd) -> None:
    """Window closed: stop serving, and stop the portable database too, unless
    a focus session is still running (the tracker keeps writing to it)."""
    httpd.shutdown()
    try:
        import db
        import focus_control
        if db.mode() == "portable" and not focus_control.tracker_running():
            import portable_db
            print(portable_db.stop())
    except Exception as e:   # closing should never show an error
        print(f"cleanup: {e}")
    # Done: exit now instead of waiting seconds for the GUI runtime to tear
    # down, so reopening right away works. The tracker is a separate process
    # and keeps running if a focus session is on.
    sys.stdout.flush()
    os._exit(0)


def main() -> None:
    mutex = claim_single_instance()   # noqa: F841 (held for the process lifetime)
    # Its own taskbar identity: shows the FocusOs icon, not Python's.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FocusOs.Desktop")

    try:
        import webview
    except ImportError:
        message_box("pywebview is not installed. Run start.bat once, or: pip install -r requirements.txt")
        sys.exit(1)

    from werkzeug.serving import make_server
    import server

    try:
        server.prepare_backend()
    except Exception as e:
        message_box(f"FocusOs could not start:\n\n{e}")
        sys.exit(1)

    port = pick_port()
    httpd = make_server("127.0.0.1", port, server.app, threaded=True)
    threading.Thread(target=httpd.serve_forever, name="flask", daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    print(f"{APP_NAME} desktop: serving {url}")

    window = webview.create_window(
        APP_NAME, url,
        width=1320, height=900, min_size=(420, 640),
        # the page's canvas colour (dark or light), so there is no flash while it loads
        background_color="#0C0A1F" if windows_uses_dark_mode() else "#EEF0FF",
        text_select=True,
    )
    window.events.closed += lambda: on_closed(httpd)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # private_mode=False + storage_path: keep localStorage (theme, goal, last
    # timer length) between launches instead of starting fresh every time.
    webview.start(private_mode=False, storage_path=str(DATA_DIR / "webview"),
                  icon=str(ICON) if ICON.exists() else None)


if __name__ == "__main__":
    # In the .exe, sys.executable is FocusOs.exe itself: a library that starts a
    # helper process (joblib/loky under scikit-learn) would re-run the whole app.
    # freeze_support() lets such a child do its job and exit instead.
    import multiprocessing
    multiprocessing.freeze_support()
    main()

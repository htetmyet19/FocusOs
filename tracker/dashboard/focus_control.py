"""Start, stop and watch a focus session from the dashboard (Windows).

The dashboard never kills the tracker. It talks to it through two named
kernel objects that the tracker creates (see tracker/src/main.cpp):

  Local\\FocusOs.Running  named mutex, exists while a tracker is running
  Local\\FocusOs.Stop     named event; setting it makes the tracker shut down
                          cleanly (flush rows, close the session)
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

TRACKER_DIR = Path(__file__).resolve().parents[1]
TRACKER_EXE = Path(os.environ.get("FOCUS_TRACKER_EXE", TRACKER_DIR / "build" / "focus_tracker.exe"))
CONFIG_PATH = Path(os.environ.get("FOCUS_CONFIG", TRACKER_DIR / "config.ini"))
LOG_PATH = TRACKER_DIR / "build" / "focus_session.log"

ALLOWED_MINUTES = (15, 25, 50, 90)

_RUNNING_MUTEX = "Local\\FocusOs.Running"
_STOP_EVENT = "Local\\FocusOs.Stop"
_SYNCHRONIZE = 0x00100000
_EVENT_MODIFY_STATE = 0x0002

_lock = threading.Lock()
_session = None   # what *this* dashboard started: {"proc", "started", "minutes", "user"}


class FocusError(Exception):
    """A request that cannot be done right now; the message is shown to the user."""


def _kernel32():
    if sys.platform != "win32":
        raise FocusError("Focus sessions can only be started from Windows.")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenMutexW.restype = ctypes.c_void_p
    k.OpenEventW.restype = ctypes.c_void_p
    k.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    k.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    k.SetEvent.argtypes = [ctypes.c_void_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


def tracker_running() -> bool:
    """True if any tracker holds the named mutex (started here or by hand)."""
    k = _kernel32()
    handle = k.OpenMutexW(_SYNCHRONIZE, False, _RUNNING_MUTEX)
    if not handle:
        return False
    k.CloseHandle(handle)
    return True


def _request_stop() -> bool:
    k = _kernel32()
    handle = k.OpenEventW(_EVENT_MODIFY_STATE, False, _STOP_EVENT)
    if not handle:
        return False
    k.SetEvent(handle)
    k.CloseHandle(handle)
    return True


def _tracker_config() -> Path:
    """The INI file the C++ tracker should read for its database connection."""
    import db
    if db.mode() == "portable":
        import portable_db
        return portable_db.RUNTIME_INI
    return CONFIG_PATH


def start(user_id: int, minutes: int) -> dict:
    global _session
    if minutes not in ALLOWED_MINUTES:
        raise FocusError(f"Choose one of {', '.join(map(str, ALLOWED_MINUTES))} minutes.")
    if not TRACKER_EXE.exists():
        raise FocusError(f"Tracker not found at {TRACKER_EXE}. Build it first (see README).")
    with _lock:
        if tracker_running():
            raise FocusError("The tracker is already running. End that session first.")
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log = open(LOG_PATH, "w", encoding="utf-8")
        proc = subprocess.Popen(
            [str(TRACKER_EXE), "--config", str(_tracker_config()), "--user", str(user_id),
             "--focus", "--minutes", str(minutes)],
            cwd=str(TRACKER_DIR), stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log.close()   # the child keeps its own handle
        _session = {"proc": proc, "started": time.time(), "minutes": minutes, "user": user_id}

    # Give it a moment: a bad config or an unreachable database exits at once.
    for _ in range(30):
        if proc.poll() is not None:
            break
        if tracker_running():
            return status()
        time.sleep(0.1)
    if proc.poll() is not None:
        with _lock:
            _session = None
        tail = LOG_PATH.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1:] or ["no output"]
        raise FocusError(f"The tracker stopped right away: {tail[0]}")
    return status()


def stop() -> dict:
    if not tracker_running():
        return status()
    _request_stop()
    # The tracker flushes its queue and closes the session; normally < 2 s.
    deadline = time.time() + 8
    while time.time() < deadline and tracker_running():
        time.sleep(0.1)
    return status()


def status() -> dict:
    global _session
    try:
        running = tracker_running()
    except FocusError as e:
        return {"supported": False, "running": False, "message": str(e)}

    with _lock:
        s = _session
        if s and s["proc"].poll() is not None and not running:
            _session = s = None          # our session finished (time up or stopped)

    out = {"supported": True, "running": running, "focus": False, "minutes": None,
           "remaining_s": None, "started_here": False,
           "tracker_found": TRACKER_EXE.exists(), "choices": list(ALLOWED_MINUTES)}
    if running and s:
        elapsed = time.time() - s["started"]
        out.update(focus=True, started_here=True, minutes=s["minutes"], user=s["user"],
                   remaining_s=max(0, round(s["minutes"] * 60 - elapsed)))
    return out

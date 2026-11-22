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

# FOCUSOS_ROOT: set by desktop.py when packaged as an .exe (the folder holding it).
TRACKER_DIR = Path(os.environ.get("FOCUSOS_ROOT") or Path(__file__).resolve().parents[2]) / "tracker"
TRACKER_EXE = Path(os.environ.get("FOCUS_TRACKER_EXE", TRACKER_DIR / "build" / "focus_tracker.exe"))
CONFIG_PATH = Path(os.environ.get("FOCUS_CONFIG", TRACKER_DIR / "config.ini"))
LOG_PATH = TRACKER_DIR / "build" / "focus_session.log"

PRESET_MINUTES = (15, 25, 50, 90)        # quick picks in the dashboard; any length in range works
MIN_MINUTES, MAX_MINUTES = 1, 480         # 1 minute to 8 hours
MIN_BREAK_EVERY, MAX_BREAK_EVERY = 10, 120
MIN_BREAK, MAX_BREAK = 1, 30

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


ON_BLOCK_FLAGS = {"close": "--close", "minimise": None}


def break_plan(minutes: int, every: int, length: int) -> list[dict]:
    """The session as blocks of focus and break, e.g. 90 / 10 every 50 ->
    focus 0-50, break 50-60, focus 60-90. Matches BreakSchedule in the tracker:
    a break is skipped if no focus time would come after it."""
    if not every or not length:
        return [{"kind": "focus", "start_min": 0, "end_min": minutes}]
    out, t = [], 0
    while t < minutes:
        focus_end = min(t + every, minutes)
        out.append({"kind": "focus", "start_min": t, "end_min": focus_end})
        if focus_end + length >= minutes:     # nothing left after the break: just finish
            if focus_end < minutes:
                out[-1]["end_min"] = minutes
            break
        out.append({"kind": "break", "start_min": focus_end, "end_min": focus_end + length})
        t = focus_end + length
    return out


def _check_length(minutes: int, break_every: int, break_min: int) -> None:
    if not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise FocusError(f"Pick a length between {MIN_MINUTES} and {MAX_MINUTES} minutes (8 hours).")
    if bool(break_every) != bool(break_min):
        raise FocusError("Set both how often to take a break and how long it lasts.")
    if break_every:
        if not MIN_BREAK_EVERY <= break_every <= MAX_BREAK_EVERY:
            raise FocusError(f"Breaks can come every {MIN_BREAK_EVERY} to {MAX_BREAK_EVERY} minutes.")
        if not MIN_BREAK <= break_min <= MAX_BREAK:
            raise FocusError(f"A break can last {MIN_BREAK} to {MAX_BREAK} minutes.")
        if break_every + break_min >= minutes:
            raise FocusError("This session is too short for a break. Make it longer or turn breaks off.")


def start(user_id: int, minutes: int, on_block: str = "close",
          break_every: int = 0, break_min: int = 0) -> dict:
    global _session
    _check_length(minutes, break_every, break_min)
    if on_block not in ON_BLOCK_FLAGS:
        raise FocusError("on_block must be 'close' or 'minimise'.")
    if not TRACKER_EXE.exists():
        raise FocusError(f"Tracker not found at {TRACKER_EXE}. Build it first (see README).")
    with _lock:
        if tracker_running():
            raise FocusError("The tracker is already running. End that session first.")
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log = open(LOG_PATH, "w", encoding="utf-8")
        args = [str(TRACKER_EXE), "--config", str(_tracker_config()),
                "--focus", "--minutes", str(minutes)]
        if ON_BLOCK_FLAGS[on_block]:
            args.append(ON_BLOCK_FLAGS[on_block])
        if break_every:
            args += ["--break-every", str(break_every), "--break", str(break_min)]
        proc = subprocess.Popen(
            args,
            cwd=str(TRACKER_DIR), stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log.close()   # the child keeps its own handle
        _session = {"proc": proc, "started": time.time(), "minutes": minutes, "user": user_id,
                    "on_block": on_block, "break_every": break_every, "break_min": break_min}

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
           "tracker_found": TRACKER_EXE.exists(), "choices": list(PRESET_MINUTES),
           "limits": {"minutes": [MIN_MINUTES, MAX_MINUTES], "break_every": [MIN_BREAK_EVERY, MAX_BREAK_EVERY],
                      "break_min": [MIN_BREAK, MAX_BREAK]}}
    if running and s:
        elapsed = time.time() - s["started"]
        plan = break_plan(s["minutes"], s["break_every"], s["break_min"])
        now_min = elapsed / 60
        current = next((p for p in plan if p["start_min"] <= now_min < p["end_min"]), plan[-1])
        on_break = current["kind"] == "break"
        out.update(focus=True, started_here=True, minutes=s["minutes"], user=s["user"], on_block=s["on_block"],
                   remaining_s=max(0, round(s["minutes"] * 60 - elapsed)),
                   break_every=s["break_every"], break_min=s["break_min"], plan=plan,
                   elapsed_s=round(elapsed), on_break=on_break,
                   phase_left_s=max(0, round(current["end_min"] * 60 - elapsed)))
    return out

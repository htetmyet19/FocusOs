"""Apps installed on this Windows PC, for the 'Add apps' picker.

The scan (list_installed_apps.ps1) reads Start menu shortcuts and Microsoft
Store packages. It takes about a second, so results are cached for a while.
"""
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

SCRIPT = Path(__file__).with_name("list_installed_apps.ps1")
CACHE_SECONDS = 10 * 60

# Never offer these: blocking them would break Windows or the tracker itself.
NEVER_BLOCK = {
    "explorer.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "msiexec.exe", "rundll32.exe",
    "control.exe", "mmc.exe", "taskmgr.exe", "conhost.exe", "windowsterminal.exe",
    "focus_tracker.exe", "python.exe", "pythonw.exe", "setup.exe", "bootstrapper.exe",
    "systemsettings.exe", "sechealthui.exe", "windowsbackupclient.exe",
}
# Uninstallers, installers, updaters and docs are not apps you'd want to block.
SKIP_NAME = re.compile(r"uninstall|setup|installer|install |update|updater|readme|release notes|"
                       r"documentation|help|website|license|repair|configure|reload configuration", re.I)
SKIP_EXE = re.compile(r"^(unins\d*|uninstall.*|setup.*|.*installer|.*updater?)\.exe$", re.I)

_lock = threading.Lock()
_cache = {"at": 0.0, "apps": []}


def _scan() -> list:
    if sys.platform != "win32":
        return []
    out = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)],
        capture_output=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    text = out.stdout.decode("utf-8-sig", errors="replace").strip()
    if not text:
        return []
    raw = json.loads(text)
    if isinstance(raw, dict):          # PowerShell emits a bare object for a single result
        raw = [raw]

    apps = {}
    for item in raw:
        exe = str(item.get("exe", "")).strip().lower()
        name = str(item.get("name", "")).strip() or exe
        if not exe.endswith(".exe") or exe in NEVER_BLOCK:
            continue
        if SKIP_EXE.match(exe) or SKIP_NAME.search(name):
            continue
        # Keep the first (desktop entries come first, with nicer names).
        apps.setdefault(exe, {"name": name, "exe": exe, "source": item.get("source", "desktop")})
    return sorted(apps.values(), key=lambda a: a["name"].lower())


def installed_apps(refresh: bool = False) -> list:
    with _lock:
        if refresh or time.time() - _cache["at"] > CACHE_SECONDS or not _cache["apps"]:
            try:
                _cache["apps"] = _scan()
            except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
                _cache["apps"] = _cache["apps"] or []
            _cache["at"] = time.time()
        return list(_cache["apps"])


def is_installed(exe: str) -> bool:
    exe = exe.lower()
    if any(a["exe"] == exe for a in installed_apps()):
        return True
    # Maybe it was installed in the last few minutes: rescan once.
    return any(a["exe"] == exe for a in installed_apps(refresh=True))


def warm_cache_in_background() -> None:
    threading.Thread(target=installed_apps, daemon=True).start()

import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
import win32gui
import win32process

POLL_SECONDS = 2
LOG_FILE = Path("activity_log.csv")

FIELDS = ["timestamp", "process_id", "process_name", "window_title"]


def get_active_window_info():
    """Return details of the currently active Windows window."""
    hwnd = win32gui.GetForegroundWindow()

    if not hwnd:
        return None

    window_title = win32gui.GetWindowText(hwnd).strip()
    _, process_id = win32process.GetWindowThreadProcessId(hwnd)

    try:
        process_name = psutil.Process(process_id).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        process_name = "unknown"

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "process_id": process_id,
        "process_name": process_name,
        "window_title": window_title or "[No window title]",
    }


def save_to_csv(record):
    """Append one monitoring record to the CSV log."""
    file_exists = LOG_FILE.exists()

    with LOG_FILE.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)

        if not file_exists:
            writer.writeheader()

        writer.writerow(record)


def main():
    print("Study Tracker started. Press Ctrl+C to stop.\n")

    current_window = get_active_window_info()

    start_time = datetime.now(timezone.utc)   # saved in log/DB
    start_tick = time.monotonic()             # used only for duration

    while True:
        time.sleep(2)
        new_window = get_active_window_info()

        if new_window and (
            new_window["process_name"] != current_window["process_name"]
            or new_window["window_title"] != current_window["window_title"]
        ):
            end_time = datetime.now(timezone.utc)
            duration_seconds = round(time.monotonic() - start_tick)

            record = {
                "process_name": current_window["process_name"],
                "window_title": current_window["window_title"],
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration_seconds,
            }

            print(record)  # Later: save this record to SQLite

            # Begin tracking the newly active window
            current_window = new_window
            start_time = end_time
            start_tick = time.monotonic()


if __name__ == "__main__":
    main()
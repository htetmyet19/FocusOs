import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
import win32gui
import win32process

POLL_SECONDS = 2
LOG_FILE = Path("activity_intervals.csv")

FIELDS = [
    "process_id",
    "process_name",
    "window_title",
    "start_time",
    "end_time",
    "duration_seconds",
]


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
        "process_id": process_id,
        "process_name": process_name,
        "window_title": window_title or "[No window title]",
    }


def save_to_csv(record):
    """Append one completed window-use interval to the CSV file."""
    file_exists = LOG_FILE.exists()

    with LOG_FILE.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)

        if not file_exists:
            writer.writeheader()

        writer.writerow(record)


def main():
    current_window = get_active_window_info()

    if not current_window:
        print("Could not detect an active window.")
        return

    start_time = datetime.now(timezone.utc)
    start_tick = time.monotonic()

    print("Tracker started. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(POLL_SECONDS)
            new_window = get_active_window_info()

            if not new_window:
                continue

            changed = (
                new_window["process_id"] != current_window["process_id"]
                or new_window["window_title"] != current_window["window_title"]
            )

            if changed:
                end_time = datetime.now(timezone.utc)

                record = {
                    "process_id": current_window["process_id"],
                    "process_name": current_window["process_name"],
                    "window_title": current_window["window_title"],
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "duration_seconds": round(time.monotonic() - start_tick),
                }

                save_to_csv(record)
                print("Saved:", record)

                current_window = new_window
                start_time = end_time
                start_tick = time.monotonic()

    except KeyboardInterrupt:
        print("\nStopping tracker...")

    finally:
        end_time = datetime.now(timezone.utc)

        record = {
            "process_id": current_window["process_id"],
            "process_name": current_window["process_name"],
            "window_title": current_window["window_title"],
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": round(time.monotonic() - start_tick),
        }

        save_to_csv(record)
        print("Final record saved.")


if __name__ == "__main__":
    main()
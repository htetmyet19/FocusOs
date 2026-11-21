"""Flask API + static file server for the FocusOs dashboard (PostgreSQL)."""
import os
from datetime import timedelta

import pandas as pd
import psycopg
from flask import Flask, jsonify, request, send_from_directory

import db
import focus_control
import installed_apps
import metrics

app = Flask(__name__, static_folder="static", static_url_path="")


@app.before_request
def _block_cross_site_writes():
    """CSRF protection for the write endpoints (one of them starts a program).

    A page on another site can make the browser send a 'simple' POST to
    127.0.0.1 without asking. Requiring a JSON content type forces a CORS
    preflight, which we never approve, and the Origin check rejects anything
    that isn't this dashboard.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
        return jsonify({"error": "Requests from other sites are not allowed."}), 403
    if not request.is_json:
        return jsonify({"error": "Send JSON (Content-Type: application/json)."}), 415
    return None


@app.errorhandler(psycopg.OperationalError)
def _database_unavailable(error):
    first_line = str(error).strip().splitlines()[0] if str(error).strip() else "connection failed"
    return jsonify({"error": f"Cannot reach PostgreSQL ({first_line}). "
                             "Is the service running and tracker/config.ini correct?"}), 503


@app.errorhandler(ValueError)
@app.errorhandler(KeyError)
def _bad_request(error):
    return jsonify({"error": str(error).strip("'\"")}), 400


@app.errorhandler(focus_control.FocusError)
def _focus_conflict(error):
    return jsonify({"error": str(error)}), 409


def _since(label: str):
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    return {"today": now.normalize(),
            "7d": now - timedelta(days=7),
            "30d": now - timedelta(days=30),
            "all": None}.get(label, now - timedelta(days=7))


def _records(df: pd.DataFrame) -> list:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif out[col].dtype == object and len(out) and hasattr(out[col].iloc[0], "isoformat"):
            out[col] = out[col].astype(str)
    return out.astype(object).where(pd.notnull(out), None).to_dict(orient="records")


def _user() -> int:
    return int(request.args.get("user", 1))


STREAK_MIN_PRODUCTIVE_S = 15 * 60   # a day counts towards the streak with >= 15 min productive


def _today_and_streak(user_id: int) -> dict:
    """Today's totals and the productive-day streak, independent of the selected range."""
    all_activity = db.activity(user_id)
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    if all_activity.empty:
        return {"today": {"tracked_s": 0.0, "productive_s": 0.0, "distracting_s": 0.0}, "streak_days": 0}

    day = all_activity.start_time.dt.normalize()
    t = all_activity[day == today].groupby("category")["seconds"].sum()

    productive_by_day = all_activity[all_activity.category == "productive"].groupby(day)["seconds"].sum()
    good_days = set(productive_by_day[productive_by_day >= STREAK_MIN_PRODUCTIVE_S].index)
    # Count back from today; if today doesn't qualify yet, the streak can still be alive from yesterday.
    cursor = today if today in good_days else today - timedelta(days=1)
    streak = 0
    while cursor in good_days:
        streak += 1
        cursor -= timedelta(days=1)

    return {
        "today": {
            "tracked_s": round(float(t.sum()), 1),
            "productive_s": round(float(t.get("productive", 0)), 1),
            "distracting_s": round(float(t.get("distracting", 0)), 1),
        },
        "streak_days": streak,
    }


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/users")
def users():
    return jsonify(_records(db.users()))


@app.get("/api/summary")
def summary():
    user_id = _user()
    since = _since(request.args.get("range", "7d"))

    sessions = db.sessions(user_id)
    if since is not None:
        sessions = sessions[sessions.start_time >= since]
    activity = db.activity(user_id, since)
    idle = db.idle_periods(user_id)
    sm = metrics.session_metrics(sessions, activity, idle)

    by_cat = activity.groupby("category")["seconds"].sum() if not activity.empty else pd.Series(dtype=float)
    total = float(by_cat.sum())

    return jsonify({
        "totals": {
            "tracked_h": round(total / 3600, 2),
            "productive_h": round(float(by_cat.get("productive", 0)) / 3600, 2),
            "neutral_h": round(float(by_cat.get("neutral", 0)) / 3600, 2),
            "distracting_h": round(float(by_cat.get("distracting", 0)) / 3600, 2),
            "avg_focus": round(float(sm.focus_score.mean()), 1) if not sm.empty else 0.0,
            "sessions": int(len(sm)),
            # Exact seconds: the hour values above round short sessions down to 0.
            "tracked_s": round(total, 1),
            "productive_s": round(float(by_cat.get("productive", 0)), 1),
            "neutral_s": round(float(by_cat.get("neutral", 0)), 1),
            "distracting_s": round(float(by_cat.get("distracting", 0)), 1),
        },
        "daily": _records(metrics.daily_totals(activity)),
        "top_apps": _records(metrics.top_apps(activity)),
        "sessions": _records(sm.sort_values("start_time", ascending=False)) if not sm.empty else [],
        "recent": _records(activity.sort_values("start_time", ascending=False)
                           [["start_time", "process_name", "window_title", "category",
                             "category_source", "seconds"]].head(100)),
        "s_max": metrics.S_MAX,
        **_today_and_streak(user_id),
    })


@app.get("/api/session/<int:session_id>")
def session_detail(session_id: int):
    user_id = _user()
    activity = db.activity(user_id)
    idle = db.idle_periods(user_id)
    act = activity[activity.session_id == session_id]
    idl = idle[idle.session_id == session_id]
    segments = [{"label": r.process_name, "kind": r.category,
                 "start": r.start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "end": r.end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "title": r.window_title} for r in act.itertuples()]
    segments += [{"label": "(idle)", "kind": "idle",
                  "start": r.start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "end": r.end_time.strftime("%Y-%m-%dT%H:%M:%SZ"), "title": ""} for r in idl.itertuples()]
    segments.sort(key=lambda s: s["start"])
    return jsonify({"session_id": session_id, "segments": segments})


@app.get("/api/processes")
def processes():
    """OS view: foreground time vs CPU time, and background CPU users."""
    data = db.process_usage(_user(), _since(request.args.get("range", "7d")))
    return jsonify({key: _records(df) for key, df in data.items()})


@app.get("/api/categories")
def categories():
    return jsonify(_records(db.app_categories(_user())))


@app.post("/api/categories")
def set_category():
    body = request.get_json()
    if body.get("label") not in db.VALID_LABELS:
        raise ValueError(f"label must be one of {db.VALID_LABELS}")
    db.set_override(int(body["user"]), int(body["app_id"]), body["label"])
    return jsonify({"ok": True})


@app.delete("/api/categories")
def reset_category():
    body = request.get_json()
    db.clear_override(int(body["user"]), int(body["app_id"]))
    return jsonify({"ok": True})


@app.get("/api/installed-apps")
def list_installed_apps():
    """Apps installed on this PC, each marked with whether this user blocks it."""
    cats = db.app_categories(_user())
    blocked = set(cats.loc[cats.effective_category == "distracting", "process_name"])
    apps = installed_apps.installed_apps(refresh=request.args.get("refresh") == "1")
    return jsonify([{**a, "blocked": a["exe"] in blocked} for a in apps])


@app.post("/api/blocked")
def add_blocked():
    body = request.get_json()
    exe = db.normalise_process_name(str(body.get("process_name", "")))
    if exe in installed_apps.NEVER_BLOCK:
        raise ValueError(f"{exe} is part of Windows or FocusOs and can't be blocked.")
    if not installed_apps.is_installed(exe):
        raise ValueError(f"{exe} isn't installed on this PC. Pick an app from the list.")
    return jsonify(db.block_app(int(body["user"]), exe))


@app.delete("/api/blocked")
def remove_blocked():
    body = request.get_json()
    db.unblock_app(int(body["user"]), int(body["app_id"]))
    return jsonify({"ok": True})


@app.get("/api/focus")
def focus_status():
    return jsonify(focus_control.status())


@app.post("/api/focus/start")
def focus_start():
    body = request.get_json()
    return jsonify(focus_control.start(int(body["user"]), int(body["minutes"])))


@app.post("/api/focus/stop")
def focus_stop():
    return jsonify(focus_control.stop())


if __name__ == "__main__":
    import sys
    import threading
    import webbrowser

    if db.mode() == "portable":
        import portable_db
        try:
            print(portable_db.start())
        except portable_db.PortableDbError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    installed_apps.warm_cache_in_background()   # so the app picker opens instantly
    url = "http://127.0.0.1:8000"
    print(f"FocusOs dashboard: {url}  (Ctrl+C to stop)")
    if os.environ.get("FOCUS_OPEN_BROWSER") == "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    # Never enable the Werkzeug debugger by default: it allows code execution.
    app.run(host="127.0.0.1", port=8000, debug=os.environ.get("FOCUS_DEBUG") == "1")

"""Flask API + static file server for the FocusOs dashboard (PostgreSQL)."""
import os
from datetime import timedelta

import pandas as pd
import psycopg
from flask import Flask, jsonify, request, send_from_directory

import db
import metrics

app = Flask(__name__, static_folder="static", static_url_path="")


@app.errorhandler(psycopg.OperationalError)
def _database_unavailable(error):
    first_line = str(error).strip().splitlines()[0] if str(error).strip() else "connection failed"
    return jsonify({"error": f"Cannot reach PostgreSQL ({first_line}). "
                             "Is the service running and tracker/config.ini correct?"}), 503


@app.errorhandler(ValueError)
@app.errorhandler(KeyError)
def _bad_request(error):
    return jsonify({"error": f"Bad request: {error}"}), 400


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
        },
        "daily": _records(metrics.daily_totals(activity)),
        "top_apps": _records(metrics.top_apps(activity)),
        "sessions": _records(sm.sort_values("start_time", ascending=False)) if not sm.empty else [],
        "recent": _records(activity.sort_values("start_time", ascending=False)
                           [["start_time", "process_name", "window_title", "category",
                             "category_source", "seconds"]].head(100)),
        "s_max": metrics.S_MAX,
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
    body = request.get_json(force=True)
    if body.get("label") not in db.VALID_LABELS:
        raise ValueError(f"label must be one of {db.VALID_LABELS}")
    db.set_override(int(body["user"]), int(body["app_id"]), body["label"])
    return jsonify({"ok": True})


@app.delete("/api/categories")
def reset_category():
    body = request.get_json(force=True)
    db.clear_override(int(body["user"]), int(body["app_id"]))
    return jsonify({"ok": True})


if __name__ == "__main__":
    # Never enable the Werkzeug debugger by default: it allows code execution.
    app.run(host="127.0.0.1", port=8000, debug=os.environ.get("FOCUS_DEBUG") == "1")

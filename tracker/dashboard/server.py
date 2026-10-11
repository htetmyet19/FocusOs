"""Flask API + static file server for the Focus Tracker dashboard."""
import os
from datetime import timedelta

import pandas as pd
from flask import Flask, jsonify, request, send_from_directory

import db
import metrics

DB_PATH = os.environ.get("FOCUS_DB", "focus.db")
app = Flask(__name__, static_folder="static", static_url_path="")


def _since(label: str):
    now = pd.Timestamp.utcnow().tz_localize(None)
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
    return out.where(pd.notnull(out), None).to_dict(orient="records")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/users")
def users():
    if not db.db_exists(DB_PATH):
        return jsonify({"error": f"No database at {DB_PATH}. Run focus_tracker first."}), 404
    return jsonify(_records(db.users(DB_PATH)))


@app.get("/api/summary")
def summary():
    user_id = int(request.args.get("user", 1))
    since = _since(request.args.get("range", "7d"))

    sessions = db.sessions(DB_PATH, user_id)
    if since is not None:
        sessions = sessions[sessions.start_time >= since]
    activity = db.activity(DB_PATH, user_id, since)
    idle = db.idle_periods(DB_PATH, user_id)
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
                           [["start_time", "process_name", "window_title", "category", "seconds"]].head(100)),
        "s_max": metrics.S_MAX,
    })


@app.get("/api/session/<int:session_id>")
def session_detail(session_id: int):
    user_id = int(request.args.get("user", 1))
    activity = db.activity(DB_PATH, user_id)
    idle = db.idle_periods(DB_PATH, user_id)
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


@app.get("/api/categories")
def categories():
    user_id = int(request.args.get("user", 1))
    return jsonify(_records(db.app_categories(DB_PATH, user_id)))


@app.post("/api/categories")
def set_category():
    body = request.get_json(force=True)
    db.set_override(DB_PATH, int(body["user"]), int(body["app_id"]), body["label"])
    return jsonify({"ok": True})


@app.delete("/api/categories")
def reset_category():
    body = request.get_json(force=True)
    db.clear_override(DB_PATH, int(body["user"]), int(body["app_id"]))
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)

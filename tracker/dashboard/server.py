"""Flask API + static file server for the FocusOs dashboard (PostgreSQL)."""
import os
from datetime import timedelta

import pandas as pd
import psycopg
from flask import Flask, jsonify, request, send_from_directory

import ai_runtime
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


# One PC, one user: everything belongs to user 1 (the database keeps the
# user_id column so the schema stays normalised, but it is always 1).
USER_ID = 1


def _user() -> int:
    return USER_ID


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
    db.set_override(USER_ID, int(body["app_id"]), body["label"])
    return jsonify({"ok": True})


@app.delete("/api/categories")
def reset_category():
    body = request.get_json()
    db.clear_override(USER_ID, int(body["app_id"]))
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
    return jsonify(db.block_app(USER_ID, exe))


@app.delete("/api/blocked")
def remove_blocked():
    body = request.get_json()
    db.unblock_app(USER_ID, int(body["app_id"]))
    return jsonify({"ok": True})


@app.get("/api/site-rules")
def list_site_rules():
    return jsonify(_records(db.site_rules(_user())))


@app.post("/api/site-rules")
def add_site_rule():
    body = request.get_json()
    return jsonify(db.add_site_rule(USER_ID, str(body.get("pattern", "")), str(body.get("category", ""))))


YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


def _youtube_title(url: str) -> str:
    """The video's title, from YouTube's public oEmbed endpoint (no API key).

    Only this fixed endpoint is ever contacted; the user's link is passed as a
    parameter, so the server can't be made to fetch arbitrary addresses.
    """
    import json
    import urllib.parse
    import urllib.request
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in YOUTUBE_HOSTS:
        raise ValueError("Only YouTube links can be looked up. For other sites, type a word from the tab title.")
    query = urllib.parse.urlencode({"url": url.strip(), "format": "json"})
    req = urllib.request.Request(f"https://www.youtube.com/oembed?{query}", headers={"User-Agent": "FocusOs"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read(200_000).decode("utf-8"))
    except Exception:
        raise ValueError("Couldn't look up that video (private, deleted, or no internet). "
                         "Type part of its title instead.")
    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("YouTube didn't return a title for that link.")
    return title


@app.post("/api/site-rules/from-link")
def add_site_rule_from_link():
    """Paste a YouTube link -> a rule for that video's title (what the tab will show)."""
    body = request.get_json()
    title = _youtube_title(str(body.get("url", "")))
    # The tab title starts with the video title; a rule matches any part of it,
    # so the first 60 characters are enough.
    rule = db.add_site_rule(USER_ID, title[:60], str(body.get("category", "")))
    return jsonify({**rule, "video_title": title})


@app.delete("/api/site-rules")
def remove_site_rule():
    body = request.get_json()
    db.delete_site_rule(USER_ID, int(body["rule_id"]))
    return jsonify({"ok": True})


@app.get("/api/ai")
def ai_status():
    return jsonify({**ai_runtime.status(), "labels": db.training_counts()})


@app.get("/api/teach")
def teach_queue():
    """Active learning: your browser titles the AI is least sure about."""
    rows = db.unlabelled_browser_titles(_user())
    return jsonify(ai_runtime.uncertain_titles(rows))


@app.post("/api/training-samples")
def add_training_sample():
    body = request.get_json()
    db.add_training_sample(str(body.get("title", "")), str(body.get("label", "")))
    return jsonify({"ok": True, "labels": db.training_counts()})


@app.post("/api/ai/retrain")
def retrain():
    started = ai_runtime.retrain_in_background(db.connection_params())
    return jsonify({"started": started, **ai_runtime.status()})


@app.get("/api/focus")
def focus_status():
    return jsonify(focus_control.status())


def _iso(ts) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ") if pd.notna(ts) else None


def _focus_summary(row, activity: pd.DataFrame, idle: pd.DataFrame) -> dict:
    """Stats for one focus session (live or finished)."""
    one = pd.DataFrame([{"session_id": row.session_id, "start_time": row.start_time,
                         "end_time": row.end_time, "focus_mode": bool(getattr(row, "focus_mode", True))}])
    sm = metrics.session_metrics(one, activity, idle).iloc[0]
    live = pd.isna(row.end_time)
    duration_s = sm.duration_min * 60
    if live:
        # Still running: measure up to now, not up to the last saved row.
        duration_s = max(duration_s, (pd.Timestamp.now(tz="UTC").tz_localize(None) - row.start_time).total_seconds())
    planned = None if pd.isna(row.planned_minutes) else int(row.planned_minutes)
    outcome = metrics.focus_outcome(bool(getattr(row, "focus_mode", True)), live, planned, duration_s)
    tracked = activity.seconds.sum() if not activity.empty else 0.0
    by_cat = activity.groupby("category")["seconds"].sum() if not activity.empty else pd.Series(dtype=float)
    return {
        "session_id": int(row.session_id),
        "start": _iso(row.start_time), "end": _iso(row.end_time),
        "live": live, "outcome": outcome, "planned_minutes": planned,
        "duration_s": round(float(duration_s), 1),
        "tracked_s": round(float(tracked), 1),
        "productive_s": round(float(by_cat.get("productive", 0)), 1),
        "neutral_s": round(float(by_cat.get("neutral", 0)), 1),
        "distracting_s": round(float(by_cat.get("distracting", 0)), 1),
        "idle_s": round(float(sm.idle_min * 60), 1),
        "switches": int(sm.switches),
        "focus_score": float(sm.focus_score),
        "blocks": int(row.blocks),
        "focus_mode": bool(getattr(row, "focus_mode", True)),
    }


@app.get("/api/focus/sessions")
def focus_history():
    """Recent focus sessions, newest first."""
    out = []
    for row in db.focus_sessions(_user()).itertuples():
        act = db.session_activity(int(row.session_id))
        idl = db.session_idle(int(row.session_id))
        out.append(_focus_summary(row, act, idl))
    return jsonify(out)


@app.get("/api/focus/session/<int:session_id>")
@app.get("/api/session/<int:session_id>")
def session_detail(session_id: int):
    """Everything about one session (focus or not): stats, apps, blocked attempts, timeline."""
    rows = db.session_row(_user(), session_id)
    if rows.empty:
        raise KeyError(f"No session {session_id} for this user")
    row = next(rows.itertuples())
    act = db.session_activity(session_id)
    idl = db.session_idle(session_id)
    blocks = db.focus_blocks(session_id)

    # A running session's current window isn't in activity_log until you
    # switch away; add it from session_live so the live view is up to date.
    live = db.live_status(session_id) if pd.isna(row.end_time) else None
    if live is not None:
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        if live.is_idle:
            idl = pd.concat([idl, pd.DataFrame([{"idle_id": -1, "session_id": session_id,
                                                 "start_time": live.current_since, "end_time": now}])],
                            ignore_index=True)
        elif isinstance(live.process_name, str) and live.process_name:
            category, source = live.category, live.category_source
            # A browser tab no website rule covers: ask the AI about it right now.
            if live.is_browser and source != "site":
                guess = ai_runtime.predict(live.window_title)
                if guess and guess[2]:
                    category, source = guess[0], "ai"
            open_row = {"log_id": -1, "session_id": session_id, "process_name": live.process_name,
                        "window_title": live.window_title, "start_time": live.current_since, "end_time": now,
                        "category": category, "category_source": source,
                        "seconds": max((now - live.current_since).total_seconds(), 0.0)}
            act = pd.concat([act, pd.DataFrame([open_row])], ignore_index=True) if not act.empty \
                else pd.DataFrame([open_row])

    summary = _focus_summary(row, act, idl)
    apps = (act.groupby(["process_name", "category"], as_index=False)["seconds"].sum()
            .sort_values("seconds", ascending=False).head(8)) if not act.empty else pd.DataFrame()
    # Per app: how often, and what was done ("closed", "minimised", "terminated").
    blocked_apps = []
    if not blocks.empty:
        for name, grp in blocks.groupby("process_name"):
            blocked_apps.append({"process_name": name, "count": int(len(grp)),
                                 "actions": {a: int(n) for a, n in grp.action.value_counts().items()}})
        blocked_apps.sort(key=lambda b: -b["count"])
    last = act.iloc[-1] if not act.empty else None

    segments = [{"label": r.process_name, "kind": r.category, "start": _iso(r.start_time),
                 "end": _iso(r.end_time), "title": r.window_title} for r in act.itertuples()]
    segments += [{"label": "(idle)", "kind": "idle", "start": _iso(r.start_time), "end": _iso(r.end_time),
                  "title": ""} for r in idl.itertuples()]
    segments.sort(key=lambda s: s["start"])

    return jsonify({
        **summary,
        "apps": [{"process_name": r.process_name, "category": r.category, "seconds": round(float(r.seconds), 1)}
                 for r in apps.itertuples()],
        "blocked_apps": blocked_apps,
        "block_events": [{"at": _iso(r.blocked_at), "process_name": r.process_name, "action": r.action}
                         for r in blocks.tail(20).itertuples()],
        "last_app": None if last is None else {"process_name": last.process_name, "title": last.window_title,
                                               "category": last.category},
        "segments": segments,
    })


@app.post("/api/focus/start")
def focus_start():
    body = request.get_json()
    return jsonify(focus_control.start(USER_ID, int(body["minutes"]),
                                       str(body.get("on_block", "close")),
                                       int(body.get("break_every") or 0), int(body.get("break_min") or 0)))


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
    ai_runtime.start_background(db.connection_params)   # label new browser tabs every minute
    url = "http://127.0.0.1:8000"
    print(f"FocusOs dashboard: {url}  (Ctrl+C to stop)")
    if os.environ.get("FOCUS_OPEN_BROWSER") == "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    # Never enable the Werkzeug debugger by default: it allows code execution.
    app.run(host="127.0.0.1", port=8000, debug=os.environ.get("FOCUS_DEBUG") == "1")

"""Derived metrics for the dashboard.

Focus score (shown in the UI):
    Focus = 100 * T_productive / (T_session - T_idle) * (1 - min(S / S_max, 0.3))
where S is app switches per active hour and S_max is the switch rate at which
the full 30% penalty applies.
"""
import pandas as pd

S_MAX = 60          # app switches per active hour that earns the maximum penalty
MAX_PENALTY = 0.3

SESSION_METRIC_COLUMNS = [
    "session_id", "start_time", "end_time", "focus_mode", "duration_min",
    "productive_min", "neutral_min", "distracting_min", "idle_min",
    "switches", "focus_score",
]


def _minutes(seconds: float) -> float:
    return round(seconds / 60.0, 1)


def count_switches(rows: pd.DataFrame) -> int:
    """Number of times the foreground *app* changed (title changes don't count)."""
    if len(rows) < 2:
        return 0
    names = rows.sort_values("start_time")["process_name"]
    return int((names != names.shift()).sum() - 1)


def focus_score(productive_s: float, session_s: float, idle_s: float, switches: int) -> float:
    active_s = session_s - idle_s
    if active_s <= 0:
        return 0.0
    switches_per_hour = switches / (active_s / 3600.0)
    penalty = min(switches_per_hour / S_MAX, MAX_PENALTY)
    score = 100.0 * (productive_s / active_s) * (1.0 - penalty)
    return round(max(0.0, min(100.0, score)), 1)


def session_metrics(sessions: pd.DataFrame, activity: pd.DataFrame,
                    idle: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for s in sessions.itertuples():
        act = activity[activity.session_id == s.session_id]
        idl = idle[idle.session_id == s.session_id]

        # An open (or crashed) session has no end_time: use the last thing we saw.
        end = s.end_time
        if pd.isna(end):
            candidates = [t for t in (act.end_time.max(), idl.end_time.max()) if pd.notna(t)]
            end = max(candidates) if candidates else s.start_time

        session_s = max((end - s.start_time).total_seconds(), 0.0)
        idle_s = float((idl.end_time - idl.start_time).dt.total_seconds().clip(lower=0).sum())
        by_cat = act.groupby("category")["seconds"].sum()
        productive_s = float(by_cat.get("productive", 0.0))
        switches = count_switches(act)

        rows.append({
            "session_id": int(s.session_id),
            "start_time": s.start_time,
            "end_time": end,
            "focus_mode": bool(s.focus_mode),
            "duration_min": _minutes(session_s),
            "productive_min": _minutes(productive_s),
            "neutral_min": _minutes(float(by_cat.get("neutral", 0.0))),
            "distracting_min": _minutes(float(by_cat.get("distracting", 0.0))),
            "idle_min": _minutes(idle_s),
            "switches": switches,
            "focus_score": focus_score(productive_s, session_s, idle_s, switches),
        })
    return pd.DataFrame(rows, columns=SESSION_METRIC_COLUMNS)


def daily_totals(activity: pd.DataFrame) -> pd.DataFrame:
    """Minutes per UTC day and category, attributed to the day the activity started."""
    if activity.empty:
        return pd.DataFrame(columns=["date", "category", "minutes"])
    df = activity.assign(date=activity.start_time.dt.strftime("%Y-%m-%d"))
    out = df.groupby(["date", "category"], as_index=False)["seconds"].sum()
    out["minutes"] = (out["seconds"] / 60.0).round(1)
    return out[["date", "category", "minutes"]]


def top_apps(activity: pd.DataFrame, limit: int = 15) -> pd.DataFrame:
    if activity.empty:
        return pd.DataFrame(columns=["process_name", "category", "minutes"])
    out = (activity.groupby(["process_name", "category"], as_index=False)["seconds"].sum()
           .sort_values("seconds", ascending=False).head(limit))
    out["minutes"] = (out["seconds"] / 60.0).round(1)
    return out[["process_name", "category", "minutes"]]

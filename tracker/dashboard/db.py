"""Queries for the dashboard, against the FocusOs PostgreSQL database.

Connection settings come from tracker/config.ini (override the path with the
FOCUS_CONFIG environment variable). With no password in that file, libpq
reads %APPDATA%\\postgresql\\pgpass.conf.

The effective category of each activity (user override > AI label > app
default) is computed by the database view vw_activity, not here.
"""
import configparser
import os
from pathlib import Path

import pandas as pd
import psycopg

VALID_LABELS = ("productive", "neutral", "distracting")

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config.ini"


def connection_params() -> dict:
    path = Path(os.environ.get("FOCUS_CONFIG", DEFAULT_CONFIG))
    parser = configparser.ConfigParser()
    parser.read(path)   # a missing file just means "use the defaults"
    section = parser["database"] if parser.has_section("database") else {}
    params = {
        "host": section.get("host", "localhost"),
        "port": int(section.get("port", 5432)),
        "user": section.get("user", "focus_user"),
        "dbname": section.get("database", "study_tracker"),
        "connect_timeout": 5,
        "application_name": "focus_dashboard",
    }
    if section.get("password"):
        params["password"] = section["password"]
    return params


def _connect() -> psycopg.Connection:
    return psycopg.connect(**connection_params())


def _query(sql: str, params=(), columns=None) -> pd.DataFrame:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        names = [d.name for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=names)
    if columns is not None and df.empty:
        df = pd.DataFrame(columns=columns)
    return df


def _naive_utc(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    """TIMESTAMPTZ arrives as timezone-aware datetimes; the dashboard works in naive UTC."""
    for col in cols:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce").dt.tz_localize(None)
    return df


def _numeric(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    """NUMERIC arrives as Python Decimal; convert for pandas arithmetic and JSON."""
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    return df


def users() -> pd.DataFrame:
    return _query("SELECT user_id, name FROM users ORDER BY user_id", columns=["user_id", "name"])


def sessions(user_id: int) -> pd.DataFrame:
    df = _query(
        "SELECT session_id, user_id, start_time, end_time, focus_mode "
        "FROM sessions WHERE user_id = %s ORDER BY start_time",
        (user_id,),
        ["session_id", "user_id", "start_time", "end_time", "focus_mode"],
    )
    df = _naive_utc(df, "start_time", "end_time")
    df["focus_mode"] = df["focus_mode"].fillna(False).astype(bool)
    return df


ACTIVITY_COLUMNS = ["log_id", "session_id", "process_name", "window_title",
                    "start_time", "end_time", "category", "category_source", "seconds"]


def activity(user_id: int, since=None) -> pd.DataFrame:
    sql = (
        "SELECT log_id, session_id, process_name, window_title, start_time, end_time, "
        "category, category_source, seconds FROM vw_activity WHERE user_id = %s"
    )
    params = [user_id]
    if since is not None:
        sql += " AND start_time >= %s"
        params.append(pd.Timestamp(since).tz_localize("UTC").to_pydatetime())
    sql += " ORDER BY start_time"
    df = _query(sql, params, ACTIVITY_COLUMNS)
    df = _naive_utc(df, "start_time", "end_time")
    return _numeric(df, "seconds")


def idle_periods(user_id: int) -> pd.DataFrame:
    df = _query(
        "SELECT i.idle_id, i.session_id, i.start_time, i.end_time "
        "FROM idle_periods i JOIN sessions s ON s.session_id = i.session_id "
        "WHERE s.user_id = %s ORDER BY i.start_time",
        (user_id,),
        ["idle_id", "session_id", "start_time", "end_time"],
    )
    return _naive_utc(df, "start_time", "end_time")


def app_categories(user_id: int) -> pd.DataFrame:
    df = _query(
        """
        SELECT a.app_id, a.process_name,
               d.label AS default_category,
               COALESCE(o.label, d.label) AS effective_category,
               (u.category_id IS NOT NULL) AS overridden
        FROM applications a
        JOIN categories d ON d.category_id = a.default_category
        LEFT JOIN user_app_category u ON u.app_id = a.app_id AND u.user_id = %s
        LEFT JOIN categories o ON o.category_id = u.category_id
        ORDER BY a.process_name
        """,
        (user_id,),
        ["app_id", "process_name", "default_category", "effective_category", "overridden"],
    )
    df["overridden"] = df["overridden"].astype(bool)
    return df


def set_override(user_id: int, app_id: int, label: str) -> None:
    if label not in VALID_LABELS:
        raise ValueError(f"label must be one of {VALID_LABELS}")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO user_app_category (user_id, app_id, category_id)
            VALUES (%s, %s, (SELECT category_id FROM categories WHERE label = %s))
            ON CONFLICT (user_id, app_id) DO UPDATE SET category_id = EXCLUDED.category_id
            """,
            (user_id, app_id, label),
        )


def clear_override(user_id: int, app_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM user_app_category WHERE user_id = %s AND app_id = %s",
            (user_id, app_id),
        )


def process_usage(user_id: int, since=None) -> dict:
    """OS views: foreground vs CPU time, and background CPU use, for the range."""
    since_sql, params = "", [user_id]
    if since is not None:
        since_sql = " AND s.start_time >= %s"
        params.append(pd.Timestamp(since).tz_localize("UTC").to_pydatetime())

    fg_cpu = _query(
        f"""
        SELECT v.process_name,
               SUM(v.foreground_seconds) AS foreground_seconds,
               SUM(v.cpu_seconds)        AS cpu_seconds,
               MAX(v.peak_cpu_percent)   AS peak_cpu_percent,
               MAX(v.peak_working_set_bytes) AS peak_working_set_bytes
        FROM vw_foreground_vs_cpu v
        JOIN sessions s ON s.session_id = v.session_id
        WHERE s.user_id = %s{since_sql}
        GROUP BY v.process_name
        ORDER BY cpu_seconds DESC, foreground_seconds DESC
        LIMIT 25
        """,
        params,
        ["process_name", "foreground_seconds", "cpu_seconds", "peak_cpu_percent",
         "peak_working_set_bytes"],
    )
    background = _query(
        f"""
        SELECT b.process_name,
               SUM(b.background_cpu_seconds) AS background_cpu_seconds,
               MAX(b.peak_cpu_percent)       AS peak_cpu_percent,
               MAX(b.max_threads)            AS max_threads,
               MAX(b.peak_working_set_bytes) AS peak_working_set_bytes,
               MODE() WITHIN GROUP (ORDER BY b.usual_priority_class) AS priority_class
        FROM vw_background_cpu b
        JOIN sessions s ON s.session_id = b.session_id
        WHERE s.user_id = %s{since_sql}
        GROUP BY b.process_name
        ORDER BY background_cpu_seconds DESC
        LIMIT 15
        """,
        params,
        ["process_name", "background_cpu_seconds", "peak_cpu_percent", "max_threads",
         "peak_working_set_bytes", "priority_class"],
    )
    fg_cpu = _numeric(fg_cpu, "foreground_seconds", "cpu_seconds", "peak_cpu_percent",
                      "peak_working_set_bytes")
    background = _numeric(background, "background_cpu_seconds", "peak_cpu_percent",
                          "max_threads", "peak_working_set_bytes")
    return {"foreground_vs_cpu": fg_cpu, "background": background}

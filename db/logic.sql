-- FocusOs report views (PostgreSQL). Run after schema.sql.
-- Re-runnable: each view is dropped and recreated.
--
-- Days are UTC days. For India time, replace 'UTC' with 'Asia/Kolkata'.

SET client_min_messages = warning;   -- hide "view does not exist" notices

DROP VIEW IF EXISTS vw_background_cpu, vw_foreground_vs_cpu, vw_daily_productivity,
                    vw_session_app_usage, vw_session_productivity, vw_activity CASCADE;


-- Every activity row with its *effective* category.
-- Priority (a design decision, change the COALESCE order to change it):
--   1. the user's own category for the app   (explicit user intent)
--   2. the AI label for this particular row   (e.g. a YouTube tab in Chrome)
--   3. the app's default category
CREATE VIEW vw_activity AS
SELECT
    l.log_id,
    l.session_id,
    s.user_id,
    l.app_id,
    a.process_name,
    l.window_title,
    l.start_time,
    l.end_time,
    EXTRACT(EPOCH FROM (l.end_time - l.start_time))::numeric AS seconds,
    c.label AS category,
    CASE
        WHEN u.category_id IS NOT NULL    THEN 'user'
        WHEN l.ai_category_id IS NOT NULL THEN 'ai'
        ELSE 'default'
    END AS category_source
FROM activity_log AS l
JOIN sessions     AS s ON s.session_id = l.session_id
JOIN applications AS a ON a.app_id = l.app_id
LEFT JOIN user_app_category AS u
       ON u.app_id = l.app_id AND u.user_id = s.user_id
JOIN categories AS c
  ON c.category_id = COALESCE(u.category_id, l.ai_category_id, a.default_category);


-- Report 1: totals and productivity per session.
CREATE VIEW vw_session_productivity AS
SELECT
    s.session_id,
    s.user_id,
    s.start_time AS session_start,
    s.end_time   AS session_end,
    s.focus_mode,
    COALESCE(SUM(v.seconds), 0)                                          AS tracked_seconds,
    COALESCE(SUM(v.seconds) FILTER (WHERE v.category = 'productive'), 0)  AS productive_seconds,
    COALESCE(SUM(v.seconds) FILTER (WHERE v.category = 'neutral'), 0)     AS neutral_seconds,
    COALESCE(SUM(v.seconds) FILTER (WHERE v.category = 'distracting'), 0) AS distracting_seconds,
    (SELECT COALESCE(SUM(EXTRACT(EPOCH FROM (i.end_time - i.start_time))), 0)
       FROM idle_periods i WHERE i.session_id = s.session_id)            AS idle_seconds,
    ROUND(100.0 * COALESCE(SUM(v.seconds) FILTER (WHERE v.category = 'productive'), 0)
          / NULLIF(SUM(v.seconds), 0), 2)                                AS productivity_percentage
FROM sessions AS s
LEFT JOIN vw_activity AS v ON v.session_id = s.session_id
GROUP BY s.session_id, s.user_id, s.start_time, s.end_time, s.focus_mode;


-- Report 2: time per app in every session.
CREATE VIEW vw_session_app_usage AS
SELECT
    session_id,
    user_id,
    process_name,
    category,
    SUM(seconds) AS total_seconds,
    make_interval(secs => SUM(seconds)) AS total_time
FROM vw_activity
GROUP BY session_id, user_id, process_name, category;


-- Report 3: productivity per day, by each activity's own start date.
CREATE VIEW vw_daily_productivity AS
SELECT
    user_id,
    (start_time AT TIME ZONE 'UTC')::date AS study_date,
    SUM(seconds) AS total_seconds,
    COALESCE(SUM(seconds) FILTER (WHERE category = 'productive'), 0)  AS productive_seconds,
    COALESCE(SUM(seconds) FILTER (WHERE category = 'distracting'), 0) AS distracting_seconds,
    ROUND(100.0 * COALESCE(SUM(seconds) FILTER (WHERE category = 'productive'), 0)
          / NULLIF(SUM(seconds), 0), 2) AS productivity_percentage
FROM vw_activity
GROUP BY user_id, (start_time AT TIME ZONE 'UTC')::date;


-- Report 4 (OS: scheduling). Foreground time vs CPU time per app and session.
-- Being in front of the user is not the same as being scheduled on a CPU:
-- an editor can be in front for an hour and use seconds of CPU, while a
-- background app can burn CPU without ever being looked at.
-- Caveat: process_samples keeps only the busiest processes per snapshot,
-- so CPU time of very quiet processes is under-counted.
CREATE VIEW vw_foreground_vs_cpu AS
WITH fg AS (
    SELECT session_id, app_id, SUM(seconds) AS foreground_seconds
    FROM vw_activity
    GROUP BY session_id, app_id
),
cpu AS (
    SELECT session_id, app_id,
           ROUND(SUM(cpu_delta_ms) / 1000.0, 2) AS cpu_seconds,
           MAX(cpu_percent)           AS peak_cpu_percent,
           MAX(working_set_bytes)     AS peak_working_set_bytes
    FROM process_samples
    GROUP BY session_id, app_id
)
SELECT
    COALESCE(fg.session_id, cpu.session_id) AS session_id,
    a.process_name,
    COALESCE(fg.foreground_seconds, 0)      AS foreground_seconds,
    COALESCE(cpu.cpu_seconds, 0)            AS cpu_seconds,
    cpu.peak_cpu_percent,
    cpu.peak_working_set_bytes,
    ROUND(COALESCE(cpu.cpu_seconds, 0) / NULLIF(fg.foreground_seconds, 0), 4)
                                            AS cpu_per_foreground_second
FROM fg
FULL OUTER JOIN cpu
       ON cpu.session_id = fg.session_id AND cpu.app_id = fg.app_id
JOIN applications AS a
  ON a.app_id = COALESCE(fg.app_id, cpu.app_id);


-- Report 5 (OS: process management). Processes using CPU while NOT in front.
CREATE VIEW vw_background_cpu AS
SELECT
    p.session_id,
    a.process_name,
    COUNT(*)                          AS samples,
    ROUND(SUM(p.cpu_delta_ms) / 1000.0, 2) AS background_cpu_seconds,
    ROUND(AVG(p.cpu_percent), 2)      AS avg_cpu_percent,
    MAX(p.cpu_percent)                AS peak_cpu_percent,
    MAX(p.thread_count)               AS max_threads,
    MAX(p.working_set_bytes)          AS peak_working_set_bytes,
    MODE() WITHIN GROUP (ORDER BY p.priority_class) AS usual_priority_class
FROM process_samples AS p
JOIN applications    AS a ON a.app_id = p.app_id
WHERE NOT p.is_foreground
GROUP BY p.session_id, a.process_name;

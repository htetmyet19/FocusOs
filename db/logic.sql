USE study_tracker;

-- Temporary rule-based categories for your existing data.
UPDATE activity_logs
SET category = CASE
    WHEN LOWER(process_name) IN (
        'code.exe', 'winword.exe', 'acrord32.exe',
        'notepad.exe', 'powerpnt.exe', 'excel.exe'
    ) THEN 'Productive'

    WHEN LOWER(process_name) IN (
        'discord.exe', 'steam.exe', 'instagram.exe'
    ) THEN 'Distracting'

    ELSE 'Neutral'
END;


-- Report 1: Productivity totals for every session.
CREATE OR REPLACE VIEW vw_session_productivity AS
SELECT
    s.id AS session_id,
    s.start_time AS session_start,
    s.end_time AS session_end,

    COALESCE(SUM(a.duration_seconds), 0) AS total_seconds,

    COALESCE(SUM(
        CASE WHEN a.category = 'Productive'
        THEN a.duration_seconds ELSE 0 END
    ), 0) AS productive_seconds,

    COALESCE(SUM(
        CASE WHEN a.category = 'Distracting'
        THEN a.duration_seconds ELSE 0 END
    ), 0) AS distracting_seconds,

    COALESCE(SUM(
        CASE WHEN a.category = 'Neutral'
        THEN a.duration_seconds ELSE 0 END
    ), 0) AS neutral_seconds,

    ROUND(
        100.0 * COALESCE(SUM(
            CASE WHEN a.category = 'Productive'
            THEN a.duration_seconds ELSE 0 END
        ), 0) / NULLIF(SUM(a.duration_seconds), 0),
        2
    ) AS productivity_percentage

FROM sessions AS s
LEFT JOIN activity_logs AS a
    ON a.session_id = s.id
GROUP BY s.id, s.start_time, s.end_time;


-- Report 2: App-wise usage in every session.
CREATE OR REPLACE VIEW vw_session_app_usage AS
SELECT
    a.session_id,
    a.process_name,
    a.category,
    SUM(a.duration_seconds) AS total_seconds,
    SEC_TO_TIME(SUM(a.duration_seconds)) AS total_time
FROM activity_logs AS a
GROUP BY
    a.session_id,
    a.process_name,
    a.category;


-- Report 3: Day-wise productivity summary.
CREATE OR REPLACE VIEW vw_daily_productivity AS
SELECT
    DATE(s.start_time) AS study_date,

    SUM(a.duration_seconds) AS total_seconds,

    SUM(
        CASE WHEN a.category = 'Productive'
        THEN a.duration_seconds ELSE 0 END
    ) AS productive_seconds,

    SUM(
        CASE WHEN a.category = 'Distracting'
        THEN a.duration_seconds ELSE 0 END
    ) AS distracting_seconds,

    ROUND(
        100.0 * SUM(
            CASE WHEN a.category = 'Productive'
            THEN a.duration_seconds ELSE 0 END
        ) / NULLIF(SUM(a.duration_seconds), 0),
        2
    ) AS productivity_percentage

FROM sessions AS s
JOIN activity_logs AS a
    ON a.session_id = s.id
GROUP BY DATE(s.start_time);
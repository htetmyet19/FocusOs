-- FocusOs PostgreSQL schema (normalised).
--
-- One-time setup is done by db/setup.ps1, or by hand in `psql -U postgres`:
--     CREATE ROLE focus_user LOGIN PASSWORD '...';
--     CREATE DATABASE study_tracker OWNER focus_user ENCODING 'UTF8';
-- then, as focus_user:
--     psql -U focus_user -d study_tracker -f db/schema.sql
--     psql -U focus_user -d study_tracker -f db/logic.sql
--
-- All times are TIMESTAMPTZ (stored as UTC).
-- Re-runnable: every CREATE uses IF NOT EXISTS, every seed ON CONFLICT DO NOTHING.

SET client_min_messages = warning;   -- hide "already exists, skipping" notices

-- ---------------------------------------------------------------- lookup data

CREATE TABLE IF NOT EXISTS categories (
    category_id  SMALLINT PRIMARY KEY,
    label        TEXT NOT NULL UNIQUE
        CHECK (label IN ('productive', 'neutral', 'distracting'))
);

CREATE TABLE IF NOT EXISTS applications (
    app_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    process_name      TEXT     NOT NULL UNIQUE
        CHECK (process_name = LOWER(process_name)),   -- always stored lower-case
    default_category  SMALLINT NOT NULL DEFAULT 2 REFERENCES categories (category_id)
);

CREATE TABLE IF NOT EXISTS users (
    user_id  BIGINT PRIMARY KEY,        -- chosen with --user, not generated
    name     TEXT   NOT NULL
);

-- A user's own category for an app; overrides the app's default.
CREATE TABLE IF NOT EXISTS user_app_category (
    user_id      BIGINT   NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    app_id       BIGINT   NOT NULL REFERENCES applications (app_id) ON DELETE CASCADE,
    category_id  SMALLINT NOT NULL REFERENCES categories (category_id),
    PRIMARY KEY (user_id, app_id)
);

-- ---------------------------------------------------------------- tracking

CREATE TABLE IF NOT EXISTS sessions (
    session_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT      NOT NULL REFERENCES users (user_id),
    start_time  TIMESTAMPTZ NOT NULL,
    end_time    TIMESTAMPTZ NULL,              -- NULL while running (or after a crash)
    focus_mode  BOOLEAN     NOT NULL DEFAULT FALSE,
    CONSTRAINT chk_session_times CHECK (end_time IS NULL OR end_time >= start_time)
);

-- One row per stretch of time a window was in the foreground.
CREATE TABLE IF NOT EXISTS activity_log (
    log_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id      BIGINT      NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    app_id          BIGINT      NOT NULL REFERENCES applications (app_id),
    window_title    TEXT        NOT NULL DEFAULT '',
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    -- Set by the title classifier for this one row (e.g. a YouTube tab in
    -- chrome.exe). NULL = the model has not labelled it.
    ai_category_id  SMALLINT    NULL REFERENCES categories (category_id),
    CONSTRAINT chk_activity_times CHECK (end_time >= start_time)
);
CREATE INDEX IF NOT EXISTS idx_activity_session_time ON activity_log (session_id, start_time);
CREATE INDEX IF NOT EXISTS idx_activity_app ON activity_log (app_id);

CREATE TABLE IF NOT EXISTS idle_periods (
    idle_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id  BIGINT      NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    start_time  TIMESTAMPTZ NOT NULL,
    end_time    TIMESTAMPTZ NOT NULL,
    CONSTRAINT chk_idle_times CHECK (end_time >= start_time)
);
CREATE INDEX IF NOT EXISTS idx_idle_session ON idle_periods (session_id);

-- Periodic snapshot of running processes (OS: process management and
-- CPU scheduling). Only the busiest processes plus the foreground one are
-- stored per snapshot, to keep the table small.
CREATE TABLE IF NOT EXISTS process_samples (
    sample_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id         BIGINT       NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    sampled_at         TIMESTAMPTZ  NOT NULL,
    app_id             BIGINT       NOT NULL REFERENCES applications (app_id),
    pid                BIGINT       NOT NULL CHECK (pid BETWEEN 0 AND 4294967295),
    parent_pid         BIGINT       NOT NULL CHECK (parent_pid BETWEEN 0 AND 4294967295),
    thread_count       INTEGER      NOT NULL CHECK (thread_count >= 0),
    base_priority      INTEGER      NOT NULL,      -- scheduler base priority (0-31)
    priority_class     TEXT         NOT NULL,      -- idle / below_normal / normal / ...
    cpu_percent        NUMERIC(6,2) NOT NULL CHECK (cpu_percent >= 0),  -- of all cores
    cpu_delta_ms       BIGINT       NOT NULL CHECK (cpu_delta_ms >= 0), -- CPU since last snapshot
    cpu_total_ms       BIGINT       NOT NULL CHECK (cpu_total_ms >= 0), -- kernel + user since start
    working_set_bytes  BIGINT       NOT NULL CHECK (working_set_bytes >= 0),
    is_foreground      BOOLEAN      NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_process_session_time ON process_samples (session_id, sampled_at);
CREATE INDEX IF NOT EXISTS idx_process_app ON process_samples (app_id);

-- Planned length of a timed session (--minutes), to show "ended early" vs "completed".
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS planned_minutes INTEGER NULL CHECK (planned_minutes > 0);

-- What a running session is doing right now: one row per running session,
-- upserted by the tracker every few seconds and deleted when it stops. Lets
-- the dashboard show the still-open window, which activity_log only gets
-- once you switch away from it.
CREATE TABLE IF NOT EXISTS session_live (
    session_id     BIGINT      PRIMARY KEY REFERENCES sessions (session_id) ON DELETE CASCADE,
    app_id         BIGINT      NULL REFERENCES applications (app_id),   -- NULL = no window / idle
    window_title   TEXT        NOT NULL DEFAULT '',
    current_since  TIMESTAMPTZ NOT NULL,
    is_idle        BOOLEAN     NOT NULL DEFAULT FALSE,
    updated_at     TIMESTAMPTZ NOT NULL
);

-- Every time Focus Mode pushed a blocked app away (OS: process control).
CREATE TABLE IF NOT EXISTS focus_blocks (
    block_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id  BIGINT      NOT NULL REFERENCES sessions (session_id) ON DELETE CASCADE,
    blocked_at  TIMESTAMPTZ NOT NULL,
    app_id      BIGINT      NOT NULL REFERENCES applications (app_id),
    action      TEXT        NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_focus_blocks_session ON focus_blocks (session_id, blocked_at);
-- minimised = window minimised; closed = asked to close (WM_CLOSE);
-- terminated = force-closed (TerminateProcess). Re-created so older
-- databases (which allowed only minimised/terminated) get 'closed' too.
ALTER TABLE focus_blocks DROP CONSTRAINT IF EXISTS focus_blocks_action_check;
ALTER TABLE focus_blocks ADD CONSTRAINT focus_blocks_action_check
    CHECK (action IN ('minimised', 'closed', 'terminated'));

-- ---------------------------------------------------------------- AI

-- Labelled window titles used to train the classifier.
-- source = 'user' for your own labels, 'demo' for generated demo data
-- (remove those with: DELETE FROM title_training_samples WHERE source = 'demo').
CREATE TABLE IF NOT EXISTS title_training_samples (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    window_title  TEXT        NOT NULL,
    label         TEXT        NOT NULL REFERENCES categories (label),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Added in 1.1; ALTER ... IF NOT EXISTS keeps older databases upgradeable.
ALTER TABLE title_training_samples ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'user';
ALTER TABLE title_training_samples ADD COLUMN IF NOT EXISTS template_group TEXT NULL;  -- demo only: for grouped validation
DO $$ BEGIN
    ALTER TABLE title_training_samples ADD CONSTRAINT chk_training_source CHECK (source IN ('user', 'demo'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Every prediction the model made (also low-confidence ones), so each row is
-- classified once and accuracy can be audited later.
CREATE TABLE IF NOT EXISTS ai_predictions (
    activity_log_id  BIGINT        PRIMARY KEY REFERENCES activity_log (log_id) ON DELETE CASCADE,
    category_id      SMALLINT      NOT NULL REFERENCES categories (category_id),
    confidence       NUMERIC(5,4)  NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    applied          BOOLEAN       NOT NULL,     -- did it change ai_category_id?
    model_name       TEXT          NOT NULL,
    predicted_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- seed data

INSERT INTO categories (category_id, label) VALUES
    (1, 'productive'), (2, 'neutral'), (3, 'distracting')
ON CONFLICT DO NOTHING;

INSERT INTO applications (process_name, default_category) VALUES
    ('code.exe', 1), ('devenv.exe', 1), ('idea64.exe', 1), ('pycharm64.exe', 1),
    ('winword.exe', 1), ('excel.exe', 1), ('powerpnt.exe', 1), ('acrobat.exe', 1),
    ('acrord32.exe', 1), ('notepad.exe', 1), ('chatgpt.exe', 1),
    ('chrome.exe', 2), ('msedge.exe', 2), ('firefox.exe', 2), ('brave.exe', 2),
    ('opera.exe', 2), ('explorer.exe', 2), ('windowsterminal.exe', 2),
    ('discord.exe', 3), ('spotify.exe', 3), ('steam.exe', 3),
    ('whatsapp.exe', 3), ('whatsapp.root.exe', 3),   -- Store build uses .root.exe
    ('telegram.exe', 3)
ON CONFLICT (process_name) DO NOTHING;

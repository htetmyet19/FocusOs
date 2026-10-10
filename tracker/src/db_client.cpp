#include "db_client.h"
#include <sqlite3.h>
#include <stdexcept>

namespace ft {

namespace {
struct Stmt {
    sqlite3_stmt* s = nullptr;
    Stmt(sqlite3* db, const char* sql) {
        if (sqlite3_prepare_v2(db, sql, -1, &s, nullptr) != SQLITE_OK)
            throw std::runtime_error(std::string("prepare failed: ") + sqlite3_errmsg(db));
    }
    ~Stmt() { sqlite3_finalize(s); }
    void text(int i, const std::string& v) { sqlite3_bind_text(s, i, v.c_str(), -1, SQLITE_TRANSIENT); }
    void i64(int i, std::int64_t v)        { sqlite3_bind_int64(s, i, v); }
    int  step()                            { return sqlite3_step(s); }
};
} // namespace

SqliteDbClient::SqliteDbClient(const std::string& path) {
    if (sqlite3_open(path.c_str(), &db_) != SQLITE_OK)
        throw std::runtime_error(std::string("cannot open db: ") + sqlite3_errmsg(db_));
    exec("PRAGMA journal_mode=WAL;");
    exec("PRAGMA foreign_keys=ON;");
    initSchema();
}

SqliteDbClient::~SqliteDbClient() { sqlite3_close(db_); }

void SqliteDbClient::exec(const char* sql) {
    char* err = nullptr;
    if (sqlite3_exec(db_, sql, nullptr, nullptr, &err) != SQLITE_OK) {
        std::string msg = err ? err : "unknown";
        sqlite3_free(err);
        throw std::runtime_error("sqlite exec failed: " + msg);
    }
}

void SqliteDbClient::initSchema() {
    exec(R"SQL(
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name    TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS categories (
    category_id INTEGER PRIMARY KEY,
    label TEXT UNIQUE NOT NULL CHECK (label IN ('productive','neutral','distracting')));
CREATE TABLE IF NOT EXISTS applications (
    app_id INTEGER PRIMARY KEY,
    process_name TEXT UNIQUE NOT NULL,
    default_category INTEGER REFERENCES categories(category_id));
CREATE TABLE IF NOT EXISTS user_app_category (
    user_id INTEGER REFERENCES users(user_id),
    app_id INTEGER REFERENCES applications(app_id),
    category_id INTEGER REFERENCES categories(category_id),
    PRIMARY KEY (user_id, app_id));
CREATE TABLE IF NOT EXISTS sessions (
    session_id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id),
    start_time TEXT NOT NULL,
    end_time TEXT,
    focus_mode INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS activity_log (
    log_id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(session_id),
    app_id INTEGER REFERENCES applications(app_id),
    window_title TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT);
CREATE TABLE IF NOT EXISTS idle_periods (
    idle_id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(session_id),
    start_time TEXT,
    end_time TEXT);
CREATE INDEX IF NOT EXISTS idx_log_session_time ON activity_log(session_id, start_time);

INSERT OR IGNORE INTO categories(category_id, label)
    VALUES (1,'productive'), (2,'neutral'), (3,'distracting');
INSERT OR IGNORE INTO applications(process_name, default_category) VALUES
    ('code.exe',1), ('devenv.exe',1), ('idea64.exe',1), ('pycharm64.exe',1),
    ('winword.exe',1), ('excel.exe',1), ('powerpnt.exe',1), ('acrobat.exe',1),
    ('chrome.exe',2), ('msedge.exe',2), ('firefox.exe',2), ('explorer.exe',2),
    ('discord.exe',3), ('spotify.exe',3), ('steam.exe',3),
    ('whatsapp.exe',3), ('telegram.exe',3);
)SQL");
}

void SqliteDbClient::ensureUser(std::int64_t userId, const std::string& name) {
    Stmt s(db_, "INSERT OR IGNORE INTO users(user_id, name) VALUES (?, ?);");
    s.i64(1, userId); s.text(2, name);
    s.step();
}

std::int64_t SqliteDbClient::openSession(std::int64_t userId, TimePoint start, bool focusMode) {
    Stmt s(db_, "INSERT INTO sessions(user_id, start_time, focus_mode) VALUES (?, ?, ?);");
    s.i64(1, userId); s.text(2, toIso8601(start)); s.i64(3, focusMode ? 1 : 0);
    if (s.step() != SQLITE_DONE) throw std::runtime_error("openSession failed");
    return sqlite3_last_insert_rowid(db_);
}

void SqliteDbClient::closeSession(std::int64_t sessionId, TimePoint end) {
    Stmt s(db_, "UPDATE sessions SET end_time = ? WHERE session_id = ?;");
    s.text(1, toIso8601(end)); s.i64(2, sessionId);
    s.step();
}

std::int64_t SqliteDbClient::getOrCreateApp(const std::string& processName) {
    {
        Stmt ins(db_, "INSERT OR IGNORE INTO applications(process_name, default_category) VALUES (?, 2);");
        ins.text(1, processName);
        ins.step();
    }
    Stmt sel(db_, "SELECT app_id FROM applications WHERE process_name = ?;");
    sel.text(1, processName);
    if (sel.step() != SQLITE_ROW) throw std::runtime_error("app lookup failed");
    return sqlite3_column_int64(sel.s, 0);
}

void SqliteDbClient::insertActivity(const std::vector<ActivityRecord>& rows) {
    if (rows.empty()) return;
    exec("BEGIN;");
    try {
        Stmt s(db_, "INSERT INTO activity_log(session_id, app_id, window_title, start_time, end_time) "
                    "VALUES (?, ?, ?, ?, ?);");
        for (const auto& r : rows) {
            sqlite3_reset(s.s);
            s.i64(1, r.sessionId);
            s.i64(2, getOrCreateApp(r.processName));
            s.text(3, r.windowTitle);
            s.text(4, toIso8601(r.start));
            s.text(5, toIso8601(r.end));
            if (s.step() != SQLITE_DONE) throw std::runtime_error("insertActivity failed");
        }
        exec("COMMIT;");
    } catch (...) {
        exec("ROLLBACK;");
        throw;
    }
}

void SqliteDbClient::insertIdle(const IdlePeriod& p) {
    Stmt s(db_, "INSERT INTO idle_periods(session_id, start_time, end_time) VALUES (?, ?, ?);");
    s.i64(1, p.sessionId); s.text(2, toIso8601(p.start)); s.text(3, toIso8601(p.end));
    s.step();
}

std::set<std::string> SqliteDbClient::distractingApps(std::int64_t userId) {
    std::set<std::string> out;
    Stmt s(db_,
        "SELECT a.process_name FROM applications a "
        "LEFT JOIN user_app_category u ON u.app_id = a.app_id AND u.user_id = ? "
        "JOIN categories c ON c.category_id = COALESCE(u.category_id, a.default_category) "
        "WHERE c.label = 'distracting';");
    s.i64(1, userId);
    while (s.step() == SQLITE_ROW)
        out.insert(reinterpret_cast<const char*>(sqlite3_column_text(s.s, 0)));
    return out;
}

} // namespace ft

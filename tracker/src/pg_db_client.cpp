#include "db_client.h"

#include <libpq-fe.h>

#include <memory>
#include <stdexcept>

namespace ft {

namespace {

// Owns a PGresult and frees it automatically (RAII).
using Result = std::unique_ptr<PGresult, decltype(&PQclear)>;

// Runs a parameterised statement ($1, $2, ...). Values are sent separately
// from the SQL text, so a window title can never be executed as SQL.
Result run(PGconn* conn, const char* sql, const std::vector<std::string>& params,
           ExecStatusType expected) {
    std::vector<const char*> values;
    values.reserve(params.size());
    for (const auto& p : params) values.push_back(p.c_str());

    Result res(PQexecParams(conn, sql, static_cast<int>(values.size()), nullptr,
                            values.empty() ? nullptr : values.data(),
                            nullptr, nullptr, 0),
               &PQclear);

    if (!res || PQresultStatus(res.get()) != expected) {
        std::string msg = res ? PQresultErrorMessage(res.get()) : "";
        if (msg.empty()) msg = PQerrorMessage(conn);
        throw std::runtime_error(std::string("PostgreSQL: ") + msg);
    }
    return res;
}

void command(PGconn* conn, const char* sql, const std::vector<std::string>& params = {}) {
    run(conn, sql, params, PGRES_COMMAND_OK);
}

Result query(PGconn* conn, const char* sql, const std::vector<std::string>& params = {}) {
    return run(conn, sql, params, PGRES_TUPLES_OK);
}

std::string ts(TimePoint tp) { return toIso8601(tp); }   // PostgreSQL reads "...Z" as UTC

} // namespace

PgDbClient::PgDbClient(DbConfig config) : config_(std::move(config)) { connect(); }

PgDbClient::~PgDbClient() {
    if (conn_) PQfinish(conn_);
}

void PgDbClient::connect() {
    const std::string port = std::to_string(config_.port);

    // Keyword/value form: no quoting problems. An empty password is left out
    // so libpq falls back to pgpass.conf.
    std::vector<const char*> keys = {"host", "port", "user", "dbname",
                                     "connect_timeout", "client_encoding", "application_name"};
    std::vector<const char*> vals = {config_.host.c_str(), port.c_str(), config_.user.c_str(),
                                     config_.database.c_str(), "5", "UTF8", "focus_tracker"};
    if (!config_.password.empty()) {
        keys.push_back("password");
        vals.push_back(config_.password.c_str());
    }
    keys.push_back(nullptr);
    vals.push_back(nullptr);

    conn_ = PQconnectdbParams(keys.data(), vals.data(), 0);
    if (!conn_ || PQstatus(conn_) != CONNECTION_OK) {
        std::string msg = conn_ ? PQerrorMessage(conn_) : "out of memory";
        if (conn_) { PQfinish(conn_); conn_ = nullptr; }
        throw std::runtime_error("cannot connect to PostgreSQL: " + msg);
    }
}

void PgDbClient::reconnect() {
    if (conn_) { PQfinish(conn_); conn_ = nullptr; }
    appIds_.clear();
    connect();
}

// BEGIN ... COMMIT; on any error ROLLBACK and rethrow. The app-id cache is
// cleared on rollback because ids created inside the failed transaction
// no longer exist.
template <typename Fn>
void PgDbClient::inTransaction(Fn&& body) {
    command(conn_, "BEGIN");
    try {
        body();
        command(conn_, "COMMIT");
    } catch (...) {
        PQclear(PQexec(conn_, "ROLLBACK"));
        appIds_.clear();
        throw;
    }
}

void PgDbClient::ensureUser(std::int64_t userId, const std::string& name) {
    command(conn_,
            "INSERT INTO users (user_id, name) VALUES ($1::bigint, $2) "
            "ON CONFLICT (user_id) DO NOTHING",
            {std::to_string(userId), name});
}

std::int64_t PgDbClient::openSession(std::int64_t userId, TimePoint start, bool focusMode) {
    auto res = query(conn_,
                     "INSERT INTO sessions (user_id, start_time, focus_mode) "
                     "VALUES ($1::bigint, $2::timestamptz, $3::boolean) RETURNING session_id",
                     {std::to_string(userId), ts(start), focusMode ? "true" : "false"});
    return std::stoll(PQgetvalue(res.get(), 0, 0));
}

void PgDbClient::closeSession(std::int64_t sessionId, TimePoint end) {
    command(conn_, "UPDATE sessions SET end_time = $2::timestamptz WHERE session_id = $1::bigint",
            {std::to_string(sessionId), ts(end)});
}

std::int64_t PgDbClient::getOrCreateApp(const std::string& processName) {
    auto it = appIds_.find(processName);
    if (it != appIds_.end()) return it->second;

    // The no-op DO UPDATE makes RETURNING give the id for existing rows too.
    auto res = query(conn_,
                     "INSERT INTO applications (process_name) VALUES ($1) "
                     "ON CONFLICT (process_name) DO UPDATE SET process_name = EXCLUDED.process_name "
                     "RETURNING app_id",
                     {toLower(processName)});
    std::int64_t id = std::stoll(PQgetvalue(res.get(), 0, 0));
    appIds_[processName] = id;
    return id;
}

void PgDbClient::insertActivity(const std::vector<ActivityRecord>& rows) {
    if (rows.empty()) return;
    inTransaction([&] {
        for (const auto& r : rows) {
            command(conn_,
                    "INSERT INTO activity_log (session_id, app_id, window_title, start_time, end_time) "
                    "VALUES ($1::bigint, $2::bigint, $3, $4::timestamptz, $5::timestamptz)",
                    {std::to_string(r.sessionId), std::to_string(getOrCreateApp(r.processName)),
                     r.windowTitle, ts(r.start), ts(r.end)});
        }
    });
}

void PgDbClient::insertIdle(const IdlePeriod& p) {
    command(conn_,
            "INSERT INTO idle_periods (session_id, start_time, end_time) "
            "VALUES ($1::bigint, $2::timestamptz, $3::timestamptz)",
            {std::to_string(p.sessionId), ts(p.start), ts(p.end)});
}

void PgDbClient::insertProcessSamples(const std::vector<ProcessSample>& rows) {
    if (rows.empty()) return;
    inTransaction([&] {
        for (const auto& s : rows) {
            command(conn_,
                    "INSERT INTO process_samples (session_id, sampled_at, app_id, pid, parent_pid, "
                    "thread_count, base_priority, priority_class, cpu_percent, cpu_delta_ms, "
                    "cpu_total_ms, working_set_bytes, is_foreground) VALUES ("
                    "$1::bigint, $2::timestamptz, $3::bigint, $4::bigint, $5::bigint, $6::int, "
                    "$7::int, $8, ROUND($9::numeric, 2), $10::bigint, $11::bigint, $12::bigint, "
                    "$13::boolean)",
                    {std::to_string(s.sessionId), ts(s.sampledAt),
                     std::to_string(getOrCreateApp(s.processName)), std::to_string(s.pid),
                     std::to_string(s.parentPid), std::to_string(s.threadCount),
                     std::to_string(s.basePriority), s.priorityClass,
                     std::to_string(s.cpuPercent), std::to_string(s.cpuDeltaMs),
                     std::to_string(s.cpuTotalMs), std::to_string(s.workingSetBytes),
                     s.isForeground ? "true" : "false"});
        }
    });
}

std::set<std::string> PgDbClient::distractingApps(std::int64_t userId) {
    auto res = query(conn_,
                     "SELECT a.process_name FROM applications a "
                     "LEFT JOIN user_app_category u ON u.app_id = a.app_id AND u.user_id = $1::bigint "
                     "JOIN categories c ON c.category_id = COALESCE(u.category_id, a.default_category) "
                     "WHERE c.label = 'distracting'",
                     {std::to_string(userId)});
    std::set<std::string> out;
    for (int i = 0; i < PQntuples(res.get()); ++i) out.insert(PQgetvalue(res.get(), i, 0));
    return out;
}

} // namespace ft

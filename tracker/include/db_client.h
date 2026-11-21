#pragma once
#include "types.h"
#include <cstdint>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

typedef struct pg_conn PGconn;   // from libpq-fe.h; keeps libpq out of this header

namespace ft {

// The only contract between the tracker logic and the database.
// SessionManager talks to this interface, so it can be tested with a fake.
class IDbClient {
public:
    virtual ~IDbClient() = default;
    virtual void         ensureUser(std::int64_t userId, const std::string& name)          = 0;
    virtual std::int64_t openSession(std::int64_t userId, TimePoint start, bool focusMode) = 0;
    virtual void         closeSession(std::int64_t sessionId, TimePoint end)               = 0;
    virtual void         insertActivity(const std::vector<ActivityRecord>& rows)          = 0;
    virtual void         insertIdle(const IdlePeriod& period)                             = 0;
    virtual void         insertProcessSamples(const std::vector<ProcessSample>& rows)     = 0;
    // Effective category == 'distracting' (user override, else app default).
    virtual std::set<std::string> distractingApps(std::int64_t userId)                    = 0;
};

struct DbConfig {
    std::string  host     = "localhost";
    unsigned int port     = 5432;
    std::string  user     = "focus_user";
    std::string  password;               // empty = use %APPDATA%\postgresql\pgpass.conf
    std::string  database = "study_tracker";
};

// PostgreSQL implementation on libpq. NOT thread-safe: one thread at a time
// (AsyncDbWriter guarantees that with a mutex). Every method throws
// std::runtime_error on failure.
class PgDbClient final : public IDbClient {
public:
    explicit PgDbClient(DbConfig config);
    ~PgDbClient() override;
    PgDbClient(const PgDbClient&)            = delete;
    PgDbClient& operator=(const PgDbClient&) = delete;

    void reconnect();

    void         ensureUser(std::int64_t userId, const std::string& name) override;
    std::int64_t openSession(std::int64_t userId, TimePoint start, bool focusMode) override;
    void         closeSession(std::int64_t sessionId, TimePoint end) override;
    void         insertActivity(const std::vector<ActivityRecord>& rows) override;
    void         insertIdle(const IdlePeriod& period) override;
    void         insertProcessSamples(const std::vector<ProcessSample>& rows) override;
    std::set<std::string> distractingApps(std::int64_t userId) override;

private:
    void         connect();
    std::int64_t getOrCreateApp(const std::string& processName);
    template <typename Fn> void inTransaction(Fn&& body);

    DbConfig config_;
    PGconn*  conn_ = nullptr;
    std::unordered_map<std::string, std::int64_t> appIds_;  // process name -> app_id cache
};

} // namespace ft

#pragma once
#include "types.h"
#include <set>
#include <string>
#include <vector>

struct sqlite3;

namespace ft {

// The only contract between the C++ tracker and everything else.
class IDbClient {
public:
    virtual ~IDbClient() = default;
    virtual void         ensureUser(std::int64_t userId, const std::string& name)              = 0;
    virtual std::int64_t openSession(std::int64_t userId, TimePoint start, bool focusMode)     = 0;
    virtual void         closeSession(std::int64_t sessionId, TimePoint end)                   = 0;
    virtual void         insertActivity(const std::vector<ActivityRecord>& rows)              = 0;
    virtual void         insertIdle(const IdlePeriod& period)                                 = 0;
    // Effective category == 'distracting' (user override, else app default).
    virtual std::set<std::string> distractingApps(std::int64_t userId)                        = 0;
};

class SqliteDbClient final : public IDbClient {
public:
    explicit SqliteDbClient(const std::string& path);
    ~SqliteDbClient() override;
    SqliteDbClient(const SqliteDbClient&)            = delete;
    SqliteDbClient& operator=(const SqliteDbClient&) = delete;

    void         ensureUser(std::int64_t userId, const std::string& name) override;
    std::int64_t openSession(std::int64_t userId, TimePoint start, bool focusMode) override;
    void         closeSession(std::int64_t sessionId, TimePoint end) override;
    void         insertActivity(const std::vector<ActivityRecord>& rows) override;
    void         insertIdle(const IdlePeriod& period) override;
    std::set<std::string> distractingApps(std::int64_t userId) override;

private:
    void         exec(const char* sql);
    void         initSchema();
    std::int64_t getOrCreateApp(const std::string& processName);

    sqlite3* db_ = nullptr;
};

} // namespace ft

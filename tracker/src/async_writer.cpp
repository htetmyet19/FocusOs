#include "async_writer.h"

#include <chrono>
#include "log.h"

namespace ft {

namespace {
template <class... Ts> struct Overloaded : Ts... { using Ts::operator()...; };
template <class... Ts> Overloaded(Ts...) -> Overloaded<Ts...>;
}

AsyncDbWriter::AsyncDbWriter(PgDbClient& db, std::size_t queueCapacity)
    : db_(db), queue_(queueCapacity) {}

AsyncDbWriter::~AsyncDbWriter() { stop(); }

void AsyncDbWriter::start() {
    if (!thread_.joinable()) thread_ = std::thread(&AsyncDbWriter::writerLoop, this);
}

void AsyncDbWriter::stop() {
    queue_.close();
    if (thread_.joinable()) thread_.join();
}

// ---- synchronous -----------------------------------------------------------

void AsyncDbWriter::ensureUser(std::int64_t userId, const std::string& name) {
    std::lock_guard<std::mutex> lock(dbMutex_);
    db_.ensureUser(userId, name);
}

std::int64_t AsyncDbWriter::openSession(std::int64_t userId, TimePoint start, bool focusMode) {
    std::lock_guard<std::mutex> lock(dbMutex_);
    return db_.openSession(userId, start, focusMode);
}

std::set<std::string> AsyncDbWriter::distractingApps(std::int64_t userId) {
    std::lock_guard<std::mutex> lock(dbMutex_);
    return db_.distractingApps(userId);
}

// ---- asynchronous ----------------------------------------------------------

void AsyncDbWriter::enqueue(Command cmd) {
    if (!queue_.push(std::move(cmd))) {
        ++dropped_;
        logError("[writer] queue closed, write dropped");
    }
}

void AsyncDbWriter::closeSession(std::int64_t sessionId, TimePoint end) { enqueue(CloseSessionCmd{sessionId, end}); }
void AsyncDbWriter::insertActivity(const std::vector<ActivityRecord>& rows) { if (!rows.empty()) enqueue(rows); }
void AsyncDbWriter::insertIdle(const IdlePeriod& period) { enqueue(period); }
void AsyncDbWriter::insertProcessSamples(const std::vector<ProcessSample>& rows) { if (!rows.empty()) enqueue(rows); }

// ---- writer thread ---------------------------------------------------------

void AsyncDbWriter::execute(const Command& cmd) {
    std::visit(Overloaded{
        [&](const std::vector<ActivityRecord>& rows) { db_.insertActivity(rows); },
        [&](const IdlePeriod& p)                     { db_.insertIdle(p); },
        [&](const std::vector<ProcessSample>& rows)  { db_.insertProcessSamples(rows); },
        [&](const CloseSessionCmd& c)                { db_.closeSession(c.sessionId, c.end); },
    }, cmd);
}

void AsyncDbWriter::writerLoop() {
    constexpr int kMaxAttempts = 3;

    // pop() blocks (no CPU use) until there is work; nullopt = closed and drained.
    while (auto cmd = queue_.pop()) {
        bool done = false;
        for (int attempt = 1; attempt <= kMaxAttempts && !done; ++attempt) {
            try {
                std::lock_guard<std::mutex> lock(dbMutex_);
                execute(*cmd);
                done = true;
            } catch (const std::exception& e) {
                logError("[writer] attempt ", attempt, " failed: ", e.what());
                if (attempt == kMaxAttempts) break;
                ++retries_;
                std::this_thread::sleep_for(std::chrono::seconds(attempt));   // back off
                try {
                    std::lock_guard<std::mutex> lock(dbMutex_);
                    db_.reconnect();
                } catch (const std::exception& re) {
                    logError("[writer] reconnect failed: ", re.what());
                }
            }
        }
        if (done) ++written_; else ++dropped_;
    }
}

AsyncDbWriter::Stats AsyncDbWriter::stats() const {
    Stats s;
    s.commandsWritten = written_;
    s.commandsDropped = dropped_;
    s.retries         = retries_;
    s.maxQueueDepth   = queue_.maxDepth();
    s.queueCapacity   = queue_.capacity();
    s.producerWaits   = queue_.producerWaits();
    return s;
}

} // namespace ft

#pragma once
// AsyncDbWriter: makes database writes non-blocking.
//
// It implements IDbClient, so SessionManager does not know it exists. Write
// calls (activity, idle, process samples, close session) are turned into
// commands and pushed into a BoundedQueue; one writer thread pops them and
// runs them on the real PgDbClient. Two producers (window sampler on the
// main thread, process sampler thread) and one consumer.
//
// Calls that need an answer (openSession, distractingApps, ensureUser) run
// synchronously. dbMutex_ makes sure only one thread uses the libpq
// connection at a time, because a PGconn is not thread-safe.

#include "bounded_queue.h"
#include "db_client.h"

#include <atomic>
#include <cstdint>
#include <mutex>
#include <thread>
#include <variant>
#include <vector>

namespace ft {

class AsyncDbWriter final : public IDbClient {
public:
    AsyncDbWriter(PgDbClient& db, std::size_t queueCapacity);
    ~AsyncDbWriter() override;

    void start();   // launch the writer thread
    void stop();    // close the queue, let the writer drain it, join

    // Synchronous (need a result).
    void         ensureUser(std::int64_t userId, const std::string& name) override;
    std::int64_t openSession(std::int64_t userId, TimePoint start, bool focusMode) override;
    std::set<std::string> distractingApps(std::int64_t userId) override;

    // Asynchronous (queued).
    void closeSession(std::int64_t sessionId, TimePoint end) override;
    void insertActivity(const std::vector<ActivityRecord>& rows) override;
    void insertIdle(const IdlePeriod& period) override;
    void insertProcessSamples(const std::vector<ProcessSample>& rows) override;

    struct Stats {
        std::uint64_t commandsWritten = 0;
        std::uint64_t commandsDropped = 0;
        std::uint64_t retries         = 0;
        std::size_t   maxQueueDepth   = 0;
        std::size_t   queueCapacity   = 0;
        std::uint64_t producerWaits   = 0;
    };
    Stats stats() const;

private:
    struct CloseSessionCmd { std::int64_t sessionId; TimePoint end; };
    using Command = std::variant<std::vector<ActivityRecord>, IdlePeriod,
                                 std::vector<ProcessSample>, CloseSessionCmd>;

    void enqueue(Command cmd);
    void writerLoop();
    void execute(const Command& cmd);

    PgDbClient&           db_;
    std::mutex            dbMutex_;
    BoundedQueue<Command> queue_;
    std::thread           thread_;

    std::atomic<std::uint64_t> written_{0};
    std::atomic<std::uint64_t> dropped_{0};
    std::atomic<std::uint64_t> retries_{0};
};

} // namespace ft

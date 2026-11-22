// Unit tests for the parts of the tracker that contain logic but no Win32 or
// database: SessionManager (with a fake IDbClient) and BoundedQueue (with
// real threads). No framework needed:  build/focus_tests.exe  or  ctest.

#include "bounded_queue.h"
#include "break_schedule.h"
#include "session_manager.h"

#include <atomic>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

namespace {

int g_failures = 0;
int g_checks   = 0;

#define CHECK(cond)                                                                 \
    do {                                                                            \
        ++g_checks;                                                                 \
        if (!(cond)) {                                                              \
            ++g_failures;                                                           \
            std::cerr << "  FAILED " << __FILE__ << ":" << __LINE__ << "  " #cond "\n"; \
        }                                                                           \
    } while (0)

using namespace ft;

// Records everything instead of talking to PostgreSQL.
struct FakeDb : IDbClient {
    std::vector<ActivityRecord> activity;
    std::vector<IdlePeriod>     idle;
    bool                        closed = false;
    TimePoint                   closedAt;

    void ensureUser(std::int64_t, const std::string&) override {}
    std::int64_t openSession(std::int64_t, TimePoint, bool) override { return 42; }
    void closeSession(std::int64_t, TimePoint end) override { closed = true; closedAt = end; }
    void insertActivity(const std::vector<ActivityRecord>& rows) override {
        activity.insert(activity.end(), rows.begin(), rows.end());
    }
    void insertIdle(const IdlePeriod& p) override { idle.push_back(p); }
    void insertProcessSamples(const std::vector<ProcessSample>&) override {}
    void insertFocusBlock(const FocusBlock&) override {}
    std::vector<LiveStatus> live;
    bool liveCleared = false;
    void updateLive(const LiveStatus& s) override { live.push_back(s); }
    void clearLive(std::int64_t) override { liveCleared = true; }
    std::set<std::string> distractingApps(std::int64_t) override { return {}; }
};

const TimePoint T0 = Clock::from_time_t(1'700'000'000);
TimePoint at(double sec) {
    return T0 + std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(sec));
}
double rel(TimePoint tp) { return secondsBetween(T0, tp); }

WindowInfo win(const std::string& exe, const std::string& title = "t") {
    WindowInfo w;
    w.valid = true; w.pid = 1; w.processName = exe; w.windowTitle = title;
    return w;
}

// Feed one sample per second: `who(t)` says which window is in front at t.
template <typename Fn>
void run(SessionManager& sm, int fromSec, int toSec, Fn who, double idleSec = 0.0) {
    for (int t = fromSec; t < toSec; ++t) sm.onSample(who(t), idleSec, at(t));
}

SessionManager::Config cfg(double minSwitch) {
    SessionManager::Config c;
    c.minSwitchSec = minSwitch;
    c.flushIntervalSec = 1e9;   // flush only on stop(), so tests see everything at the end
    return c;
}

void test_blip_is_absorbed() {
    std::cout << "blip shorter than minSwitchSec is absorbed\n";
    FakeDb db;
    SessionManager sm(db, 1, false, cfg(2.0));
    sm.start(at(0));
    // code.exe for 10 s, explorer (Alt+Tab) for ONE sample, code.exe again
    run(sm, 0, 20, [](int t) { return t == 10 ? win("explorer.exe", "Task Switching") : win("code.exe"); });
    sm.stop(at(20));

    CHECK(db.activity.size() == 1);
    CHECK(db.activity[0].processName == "code.exe");
    CHECK(std::abs(rel(db.activity[0].start) - 0) < 1e-6);
    CHECK(std::abs(rel(db.activity[0].end) - 20) < 1e-6);
}

void test_real_switch_is_backdated() {
    std::cout << "real switch is confirmed and backdated to when it began\n";
    FakeDb db;
    SessionManager sm(db, 1, false, cfg(2.0));
    sm.start(at(0));
    run(sm, 0, 30, [](int t) { return t < 10 ? win("code.exe") : win("chrome.exe"); });
    sm.stop(at(30));

    CHECK(db.activity.size() == 2);
    CHECK(db.activity[0].processName == "code.exe");
    CHECK(std::abs(rel(db.activity[0].end) - 10) < 1e-6);     // not 12: backdated
    CHECK(db.activity[1].processName == "chrome.exe");
    CHECK(std::abs(rel(db.activity[1].start) - 10) < 1e-6);
    CHECK(std::abs(rel(db.activity[1].end) - 30) < 1e-6);
}

void test_flicker_through_several_windows() {
    std::cout << "A -> B (blip) -> C: B is absorbed, C starts when it appeared\n";
    FakeDb db;
    SessionManager sm(db, 1, false, cfg(2.0));
    sm.start(at(0));
    run(sm, 0, 20, [](int t) {
        if (t < 10) return win("code.exe");
        if (t == 10) return win("discord.exe");
        return win("chrome.exe");
    });
    sm.stop(at(20));

    CHECK(db.activity.size() == 2);
    CHECK(db.activity[0].processName == "code.exe");
    CHECK(std::abs(rel(db.activity[0].end) - 11) < 1e-6);     // discord's second stays with code
    CHECK(db.activity[1].processName == "chrome.exe");
    CHECK(std::abs(rel(db.activity[1].start) - 11) < 1e-6);
}

void test_no_debounce_switches_immediately() {
    std::cout << "minSwitchSec = 0 keeps the old behaviour\n";
    FakeDb db;
    SessionManager sm(db, 1, false, cfg(0.0));
    sm.start(at(0));
    run(sm, 0, 20, [](int t) { return t == 10 ? win("explorer.exe") : win("code.exe"); });
    sm.stop(at(20));
    CHECK(db.activity.size() == 3);
}

void test_title_change_is_a_new_activity() {
    std::cout << "same app, different title (browser tab) is a new row\n";
    FakeDb db;
    SessionManager sm(db, 1, false, cfg(2.0));
    sm.start(at(0));
    run(sm, 0, 20, [](int t) { return win("chrome.exe", t < 10 ? "Stack Overflow" : "YouTube"); });
    sm.stop(at(20));
    CHECK(db.activity.size() == 2);
    CHECK(db.activity[1].windowTitle == "YouTube");
}

void test_idle_period() {
    std::cout << "idle: activity ends when input stopped, idle period recorded\n";
    FakeDb db;
    SessionManager::Config c = cfg(2.0);
    c.idleThresholdSec = 120.0;
    SessionManager sm(db, 1, false, c);
    sm.start(at(0));

    // Active 0-99 s, then no input from t=100: idle seconds grow 0,1,2,...
    for (int t = 0; t < 100; ++t) sm.onSample(win("code.exe"), 0.0, at(t));
    for (int t = 100; t <= 230; ++t) sm.onSample(win("code.exe"), t - 100.0, at(t));
    CHECK(sm.isIdle());
    sm.onSample(win("code.exe"), 0.0, at(240));                 // user is back
    CHECK(!sm.isIdle());
    sm.stop(at(300));

    CHECK(db.idle.size() == 1);
    CHECK(std::abs(rel(db.idle[0].start) - 100) < 1e-6);        // backdated to last input
    CHECK(std::abs(rel(db.idle[0].end) - 240) < 1e-6);
    CHECK(db.activity.size() == 2);
    CHECK(std::abs(rel(db.activity[0].end) - 100) < 1e-6);
    CHECK(std::abs(rel(db.activity[1].start) - 240) < 1e-6);
}

void test_stop_closes_session() {
    std::cout << "stop() flushes rows and closes the session\n";
    FakeDb db;
    SessionManager sm(db, 1, false, cfg(2.0));
    sm.start(at(0));
    run(sm, 0, 5, [](int) { return win("code.exe"); });
    sm.stop(at(5));
    CHECK(db.closed);
    CHECK(std::abs(rel(db.closedAt) - 5) < 1e-6);
    CHECK(db.activity.size() == 1);
    CHECK(sm.pendingRows() == 0);
}

void test_live_status() {
    std::cout << "live status: the open window is published every 5 s and cleared at stop\n";
    FakeDb db;
    SessionManager::Config c = cfg(2.0);
    c.liveIntervalSec = 5.0;
    SessionManager sm(db, 1, false, c);
    sm.start(at(0));
    run(sm, 0, 20, [](int) { return win("code.exe", "main.cpp"); });
    // samples at t = 0..19 -> published at 0, 5, 10, 15
    CHECK(db.live.size() == 4);
    CHECK(db.live.back().processName == "code.exe");
    CHECK(std::abs(rel(db.live.back().since) - 0) < 1e-6);    // still the same open window
    CHECK(db.activity.empty());                              // nothing closed yet: that's why live exists
    sm.stop(at(20));
    CHECK(db.liveCleared);
}

void test_queue_many_producers() {
    std::cout << "BoundedQueue: 4 producers x 20000 items, capacity 8, 1 consumer\n";
    constexpr int kProducers = 4, kItems = 20000;
    BoundedQueue<std::int64_t> q(8);

    std::atomic<std::int64_t> received{0}, sum{0};
    std::size_t depthViolations = 0;
    std::thread consumer([&] {
        while (auto v = q.pop()) {
            if (q.size() > q.capacity()) ++depthViolations;
            ++received;
            sum += *v;
        }
    });

    std::vector<std::thread> producers;
    for (int p = 0; p < kProducers; ++p)
        producers.emplace_back([&, p] {
            for (int i = 1; i <= kItems; ++i) q.push(static_cast<std::int64_t>(p) * kItems + i);
        });
    for (auto& t : producers) t.join();
    q.close();
    consumer.join();

    const std::int64_t n = std::int64_t(kProducers) * kItems;
    CHECK(received == n);                       // nothing lost
    CHECK(sum == n * (n + 1) / 2);              // nothing duplicated or corrupted
    CHECK(q.maxDepth() <= q.capacity());        // buffer bound respected
    CHECK(depthViolations == 0);
    std::cout << "  peak depth " << q.maxDepth() << "/" << q.capacity()
              << ", producer waits (buffer full) " << q.producerWaits() << "\n";
}

void test_queue_close_wakes_consumer() {
    std::cout << "BoundedQueue: close() wakes a blocked consumer\n";
    BoundedQueue<int> q(2);
    std::atomic<bool> gotNullopt{false};
    std::thread consumer([&] { gotNullopt = !q.pop().has_value(); });
    std::this_thread::sleep_for(std::chrono::milliseconds(50));   // let it block
    q.close();
    consumer.join();
    CHECK(gotNullopt);
    CHECK(!q.push(1));                          // closed queue refuses new items
}

} // namespace

void test_break_schedule() {
    std::cout << "break schedule\n";
    // 90 min, a 10 min break every 50 min: focus 0-50, break 50-60, focus 60-90.
    BreakSchedule b{50 * 60.0, 10 * 60.0, 90 * 60.0};
    CHECK(b.enabled());
    CHECK(!b.onBreak(0));
    CHECK(!b.onBreak(49 * 60.0));
    CHECK(b.onBreak(50 * 60.0));
    CHECK(b.onBreak(59 * 60.0));
    CHECK(std::fabs(b.breakLeft(55 * 60.0) - 5 * 60.0) < 1e-6);
    CHECK(!b.onBreak(60 * 60.0));
    CHECK(!b.onBreak(89 * 60.0));
    CHECK(b.breakLeft(70 * 60.0) == 0.0);

    // 120 min, 5 min every 25: breaks at 25, 55, 85; the one at 115 would run
    // into the end of the session, so it is skipped.
    BreakSchedule p{25 * 60.0, 5 * 60.0, 120 * 60.0};
    CHECK(p.onBreak(27 * 60.0));
    CHECK(p.onBreak(87 * 60.0));
    CHECK(!p.onBreak(116 * 60.0));

    BreakSchedule off{};
    CHECK(!off.enabled());
    CHECK(!off.onBreak(30 * 60.0));
}

int main() {
    test_blip_is_absorbed();
    test_real_switch_is_backdated();
    test_flicker_through_several_windows();
    test_no_debounce_switches_immediately();
    test_title_change_is_a_new_activity();
    test_idle_period();
    test_stop_closes_session();
    test_live_status();
    test_queue_many_producers();
    test_queue_close_wakes_consumer();
    test_break_schedule();

    std::cout << "\n" << (g_checks - g_failures) << "/" << g_checks << " checks passed\n";
    return g_failures == 0 ? 0 : 1;
}

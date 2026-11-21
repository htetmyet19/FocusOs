#pragma once
#include "db_client.h"
#include "types.h"
#include <optional>
#include <vector>

namespace ft {

// Turns 1-second samples into sessions, activity_log rows and idle_periods.
// Contains no Win32: fully unit-testable with a fake IDbClient (tests/).
//
// Switch debouncing (hysteresis): a different window only becomes the new
// activity after it has stayed in front for minSwitchSec. The switch is then
// backdated to when it first appeared, so no time is lost. Shorter blips
// (Alt+Tab passing through windows, "Task Switching", a notification
// stealing focus for a moment) are absorbed into the current activity
// instead of becoming noise rows and inflating the switch count.
class SessionManager {
public:
    struct Config {
        double      idleThresholdSec = 120.0; // no input for this long => idle
        double      minSwitchSec     = 2.0;   // a window must stay this long to count (0 = off)
        double      flushIntervalSec = 15.0;  // commit buffered rows at least this often
        std::size_t flushRows        = 50;    // ...or when the buffer reaches this size
    };

    // Two constructors instead of `Config cfg = {}`: GCC rejects a default
    // argument of a nested type with member initializers inside the class.
    SessionManager(IDbClient& db, std::int64_t userId, bool focusMode);
    SessionManager(IDbClient& db, std::int64_t userId, bool focusMode, Config cfg);

    void start(TimePoint now);
    void onSample(const WindowInfo& win, double idleSeconds, TimePoint now);
    void stop(TimePoint now);

    std::int64_t sessionId() const { return session_.id; }
    bool         isIdle()    const { return idle_; }
    std::size_t  pendingRows() const { return buffer_.size(); }

private:
    void closeCurrentActivity(TimePoint at);
    void openActivity(const WindowInfo& win, TimePoint at);
    void flush();
    void maybeFlush(TimePoint now);

    IDbClient&   db_;
    Config       cfg_;
    Session      session_;
    bool         running_ = false;

    std::optional<WindowInfo> current_;
    TimePoint                 currentStart_;

    std::optional<WindowInfo> candidate_;        // a different window, not yet confirmed
    TimePoint                 candidateSince_;

    bool      idle_ = false;
    TimePoint idleStart_;

    std::vector<ActivityRecord> buffer_;
    TimePoint                   lastFlush_;
};

} // namespace ft

#include "session_manager.h"

namespace ft {

SessionManager::SessionManager(IDbClient& db, std::int64_t userId, bool focusMode, Config cfg)
    : db_(db), cfg_(cfg) {
    session_.userId    = userId;
    session_.focusMode = focusMode;
}

void SessionManager::start(TimePoint now) {
    session_.start = now;
    session_.id    = db_.openSession(session_.userId, now, session_.focusMode);
    lastFlush_     = now;
    running_       = true;
}

void SessionManager::openActivity(const WindowInfo& win, TimePoint at) {
    if (!win.valid) { current_.reset(); return; }
    current_      = win;
    currentStart_ = at;
}

void SessionManager::closeCurrentActivity(TimePoint at) {
    if (!current_) return;
    if (secondsBetween(currentStart_, at) > 0.0) {
        buffer_.push_back({session_.id, current_->processName, current_->windowTitle, currentStart_, at});
    }
    current_.reset();
}

void SessionManager::onSample(const WindowInfo& win, double idleSeconds, TimePoint now) {
    if (!running_) return;

    const bool idleNow = idleSeconds >= cfg_.idleThresholdSec;

    if (idleNow && !idle_) {
        // Idle actually began idleSeconds ago; credit the activity only up to that point.
        TimePoint began = now - std::chrono::duration_cast<Clock::duration>(
                                    std::chrono::duration<double>(idleSeconds));
        if (began < currentStart_) began = currentStart_;
        closeCurrentActivity(began);
        idle_      = true;
        idleStart_ = began;
    } else if (!idleNow && idle_) {
        db_.insertIdle({session_.id, idleStart_, now});
        idle_ = false;
        openActivity(win, now);
    } else if (!idle_) {
        if (!current_) {
            openActivity(win, now);
        } else if (*current_ != win) {
            closeCurrentActivity(now);
            openActivity(win, now);
        }
    }

    maybeFlush(now);
}

void SessionManager::stop(TimePoint now) {
    if (!running_) return;
    if (idle_) {
        db_.insertIdle({session_.id, idleStart_, now});
        idle_ = false;
    } else {
        closeCurrentActivity(now);
    }
    flush();
    db_.closeSession(session_.id, now);
    session_.end = now;
    running_     = false;
}

void SessionManager::maybeFlush(TimePoint now) {
    if (buffer_.size() >= cfg_.flushRows ||
        (!buffer_.empty() && secondsBetween(lastFlush_, now) >= cfg_.flushIntervalSec)) {
        flush();
        lastFlush_ = now;
    }
}

void SessionManager::flush() {
    if (buffer_.empty()) return;
    db_.insertActivity(buffer_);
    buffer_.clear();
}

} // namespace ft

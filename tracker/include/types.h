#pragma once
#include <chrono>
#include <cstdint>
#include <optional>
#include <string>

namespace ft {

using Clock     = std::chrono::system_clock;
using TimePoint = Clock::time_point;

struct WindowInfo {
    bool          valid = false;     // false on lock screen / no foreground window
    std::uint32_t pid   = 0;
    std::string   processName;       // lower-case, e.g. "chrome.exe"
    std::string   windowTitle;

    bool operator==(const WindowInfo& o) const {
        return valid == o.valid && processName == o.processName && windowTitle == o.windowTitle;
    }
    bool operator!=(const WindowInfo& o) const { return !(*this == o); }
};

struct ActivityRecord {
    std::int64_t sessionId = 0;
    std::string  processName;
    std::string  windowTitle;
    TimePoint    start;
    TimePoint    end;
};

struct IdlePeriod {
    std::int64_t sessionId = 0;
    TimePoint    start;
    TimePoint    end;
};

// One process in one snapshot (OS: process management + CPU scheduling).
struct ProcessSample {
    std::int64_t  sessionId      = 0;
    TimePoint     sampledAt;
    std::uint32_t pid            = 0;
    std::uint32_t parentPid      = 0;
    std::string   processName;           // lower-case
    std::uint32_t threadCount    = 0;
    std::int32_t  basePriority   = 0;    // scheduler base priority, 0-31
    std::string   priorityClass;         // "normal", "high", ...
    double        cpuPercent     = 0.0;  // share of ALL cores since last snapshot
    std::int64_t  cpuDeltaMs     = 0;    // kernel + user CPU since last snapshot
    std::int64_t  cpuTotalMs     = 0;    // kernel + user CPU since process start
    std::uint64_t workingSetBytes = 0;
    bool          isForeground   = false;
};

// What a running session is doing right now (the still-open window).
struct LiveStatus {
    std::int64_t sessionId = 0;
    std::string  processName;     // empty = no window
    std::string  windowTitle;
    TimePoint    since;           // when this window came to the front (or idle began)
    TimePoint    updatedAt;
    bool         idle = false;
};

// Focus Mode pushed a blocked app away.
struct FocusBlock {
    std::int64_t sessionId = 0;
    TimePoint    at;
    std::string  processName;   // lower-case
    std::string  action = "minimised";   // "minimised" | "closed" | "terminated"
};

struct Session {
    std::int64_t             id        = 0;
    std::int64_t             userId    = 0;
    TimePoint                start;
    std::optional<TimePoint> end;
    bool                     focusMode = false;
};

std::string toIso8601(TimePoint tp);                 // "YYYY-MM-DDTHH:MM:SSZ" (UTC)
double      secondsBetween(TimePoint a, TimePoint b); // b - a
std::string toLower(std::string s);

} // namespace ft

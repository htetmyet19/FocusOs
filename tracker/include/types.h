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

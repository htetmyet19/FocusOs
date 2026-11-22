#pragma once
#include <cmath>

namespace ft {

// Breaks inside a long focus session, e.g. 90 min with "10 min every 50 min":
//
//   |---- focus 50 ----|- break 10 -|---- focus 30 ----|
//
// The total length includes the breaks. A break is only taken if some focus
// time comes after it: a break that would run into the end of the session is
// skipped (the session just ends). During a break the blocked apps are allowed.
// Pure arithmetic on "seconds since the session started", so it is unit-tested.
struct BreakSchedule {
    double everySec = 0.0;   // focus time before each break (0 = no breaks)
    double breakSec = 0.0;   // length of each break
    double totalSec = 0.0;   // whole session, breaks included (0 = open-ended)

    bool enabled() const { return everySec > 0.0 && breakSec > 0.0; }

    bool onBreak(double elapsedSec) const {
        if (!enabled() || elapsedSec < 0.0) return false;
        const double cycle = everySec + breakSec;
        const double start = std::floor(elapsedSec / cycle) * cycle;   // start of this cycle
        const double phase = elapsedSec - start;
        if (phase < everySec) return false;                           // focusing
        return totalSec <= 0.0 || start + cycle < totalSec;           // focus follows the break
    }

    // Seconds until the current break ends (0 if not on a break).
    double breakLeft(double elapsedSec) const {
        if (!onBreak(elapsedSec)) return 0.0;
        const double cycle = everySec + breakSec;
        return cycle - std::fmod(elapsedSec, cycle);
    }
};

} // namespace ft

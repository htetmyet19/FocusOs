#pragma once
#include "types.h"
#include <cstdint>
#include <set>
#include <string>

namespace ft {

// Focus Mode: keeps blocked apps out of the way (OS: process control).
//
//   Minimise   minimise the blocked app's window
//   Close      ask it to close like clicking its X (WM_CLOSE to its windows),
//              so it can save; if it is still in front after graceSec,
//              force it closed (TerminateProcess)
//   Terminate  force it closed immediately
class FocusMode {
public:
    enum class Policy { Minimise, Close, Terminate };
    enum class Action { None, Minimised, Closed, ForceClosed, Failed };

    FocusMode(std::set<std::string> blocked, Policy policy, double graceSec = 1.5);

    bool   isBlocked(const std::string& processName) const;   // platform-neutral
    Action enforce(const WindowInfo& win, TimePoint now);      // what it did, if anything

    const std::set<std::string>& blocked() const { return blocked_; }
    Policy policy() const { return policy_; }

    static const char* actionName(Action a);   // "minimised" / "closed" / "terminated"

private:
    std::set<std::string> blocked_;   // lower-case process names
    Policy                policy_;
    double                graceSec_;
    std::uint32_t         pendingPid_ = 0;   // asked to close, waiting to see if it did
    TimePoint             pendingSince_;
};

} // namespace ft

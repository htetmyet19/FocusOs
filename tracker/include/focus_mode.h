#pragma once
#include "types.h"
#include <set>
#include <string>

namespace ft {

class FocusMode {
public:
    FocusMode(std::set<std::string> blocked, bool terminate);

    bool isBlocked(const std::string& processName) const;   // platform-neutral
    bool enforce(const WindowInfo& win) const;              // returns true if it acted

    const std::set<std::string>& blocked() const { return blocked_; }

private:
    std::set<std::string> blocked_;   // lower-case process names
    bool                  terminate_; // false = minimise, true = kill
};

} // namespace ft

#pragma once
#include "types.h"

namespace ft {

// Reads the foreground window + owning process. Win32 on Windows, stub elsewhere.
class WindowMonitor {
public:
    WindowInfo poll() const;
};

} // namespace ft

#pragma once

namespace ft {

// Seconds since the last keyboard/mouse input (GetLastInputInfo). Stub returns 0 elsewhere.
class IdleDetector {
public:
    double idleSeconds() const;
};

} // namespace ft

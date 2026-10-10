#include "idle_detector.h"

#ifdef _WIN32
#include <windows.h>

namespace ft {
double IdleDetector::idleSeconds() const {
    LASTINPUTINFO lii{};
    lii.cbSize = sizeof(LASTINPUTINFO);
    if (!GetLastInputInfo(&lii)) return 0.0;
    DWORD elapsedMs = GetTickCount() - lii.dwTime;   // unsigned wrap-around is safe here
    return elapsedMs / 1000.0;
}
}

#else
namespace ft {
double IdleDetector::idleSeconds() const { return 0.0; }  // non-Windows stub
}
#endif

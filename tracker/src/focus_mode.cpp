#include "focus_mode.h"

#ifdef _WIN32
#include <windows.h>
#endif

namespace ft {

FocusMode::FocusMode(std::set<std::string> blocked, bool terminate)
    : terminate_(terminate) {
    for (auto& b : blocked) blocked_.insert(toLower(b));
}

bool FocusMode::isBlocked(const std::string& processName) const {
    return blocked_.count(toLower(processName)) > 0;
}

bool FocusMode::enforce(const WindowInfo& win) const {
    if (!win.valid || !isBlocked(win.processName)) return false;
#ifdef _WIN32
    if (terminate_) {
        HANDLE h = OpenProcess(PROCESS_TERMINATE, FALSE, win.pid);
        if (!h) return false;
        BOOL ok = TerminateProcess(h, 1);
        CloseHandle(h);
        return ok != 0;
    }
    HWND hwnd = GetForegroundWindow();
    if (!hwnd) return false;
    return ShowWindow(hwnd, SW_MINIMIZE) != 0;
#else
    return false;
#endif
}

} // namespace ft

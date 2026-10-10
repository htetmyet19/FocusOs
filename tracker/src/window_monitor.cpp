#include "window_monitor.h"

#ifdef _WIN32
#include <windows.h>
#include <string>

namespace ft {

WindowInfo WindowMonitor::poll() const {
    WindowInfo info;
    HWND hwnd = GetForegroundWindow();
    if (!hwnd) return info;                       // lock screen / nothing focused

    char title[512] = {0};
    GetWindowTextA(hwnd, title, sizeof(title));
    info.windowTitle = title;

    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    info.pid = pid;

    HANDLE proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (proc) {
        char path[MAX_PATH] = {0};
        DWORD size = MAX_PATH;
        if (QueryFullProcessImageNameA(proc, 0, path, &size)) {
            std::string full(path, size);
            auto slash = full.find_last_of("\\/");
            info.processName = toLower(slash == std::string::npos ? full : full.substr(slash + 1));
        }
        CloseHandle(proc);
    }
    if (info.processName.empty()) info.processName = "unknown.exe";
    info.valid = true;
    return info;
}

} // namespace ft

#else
namespace ft {
WindowInfo WindowMonitor::poll() const { return WindowInfo{}; }  // non-Windows stub
}
#endif

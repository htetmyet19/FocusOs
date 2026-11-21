#include "window_monitor.h"

#ifdef _WIN32
#include <windows.h>
#include <string>
#include <vector>

namespace ft {

namespace {
// Window titles and paths are UTF-16 on Windows. Convert to UTF-8 so that
// non-English titles (Hindi, Burmese, emoji...) are stored correctly.
// The old *A functions used the ANSI code page and turned them into '?'.
std::string toUtf8(const std::wstring& text) {
    if (text.empty()) return {};
    int size = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                                   nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<std::size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                        out.data(), size, nullptr, nullptr);
    return out;
}
} // namespace

WindowInfo WindowMonitor::poll() const {
    WindowInfo info;
    HWND hwnd = GetForegroundWindow();
    if (!hwnd) return info;                       // lock screen / nothing focused

    int length = GetWindowTextLengthW(hwnd);
    if (length > 0) {
        std::vector<wchar_t> title(static_cast<std::size_t>(length) + 1);
        int copied = GetWindowTextW(hwnd, title.data(), static_cast<int>(title.size()));
        info.windowTitle = toUtf8(std::wstring(title.data(), static_cast<std::size_t>(copied)));
    }

    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    info.pid = pid;

    HANDLE proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (proc) {
        std::vector<wchar_t> path(1024);
        DWORD size = static_cast<DWORD>(path.size());
        if (QueryFullProcessImageNameW(proc, 0, path.data(), &size)) {
            std::wstring full(path.data(), size);
            auto slash = full.find_last_of(L"\\/");
            info.processName = toLower(toUtf8(slash == std::wstring::npos ? full : full.substr(slash + 1)));
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

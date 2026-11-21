#include "focus_mode.h"

#ifdef _WIN32
#include <windows.h>
#endif

namespace ft {

FocusMode::FocusMode(std::set<std::string> blocked, Policy policy, double graceSec)
    : policy_(policy), graceSec_(graceSec) {
    for (auto& b : blocked) blocked_.insert(toLower(b));
}

bool FocusMode::isBlocked(const std::string& processName) const {
    return blocked_.count(toLower(processName)) > 0;
}

const char* FocusMode::actionName(Action a) {
    switch (a) {
    case Action::Minimised:   return "minimised";
    case Action::Closed:      return "closed";
    case Action::ForceClosed: return "terminated";
    default:                  return "";
    }
}

#ifdef _WIN32
namespace {

bool terminatePid(std::uint32_t pid) {
    HANDLE h = OpenProcess(PROCESS_TERMINATE, FALSE, pid);
    if (!h) return false;                      // e.g. an elevated app: access denied
    BOOL ok = TerminateProcess(h, 1);
    CloseHandle(h);
    return ok != 0;
}

// Send WM_CLOSE to every visible top-level window of the process: the same
// message Windows sends when you click a window's X.
struct CloseCtx { DWORD pid; int sent; };
BOOL CALLBACK closeWindowsOf(HWND hwnd, LPARAM lp) {
    auto* ctx = reinterpret_cast<CloseCtx*>(lp);
    DWORD owner = 0;
    GetWindowThreadProcessId(hwnd, &owner);
    if (owner == ctx->pid && IsWindowVisible(hwnd) && GetWindow(hwnd, GW_OWNER) == nullptr) {
        PostMessageW(hwnd, WM_CLOSE, 0, 0);    // asynchronous: never blocks on a hung app
        ++ctx->sent;
    }
    return TRUE;
}

} // namespace
#endif

FocusMode::Action FocusMode::enforce(const WindowInfo& win, TimePoint now) {
    if (!win.valid || !isBlocked(win.processName)) {
        pendingPid_ = 0;                        // the blocked window went away: closing worked
        return Action::None;
    }
#ifdef _WIN32
    switch (policy_) {
    case Policy::Minimise: {
        HWND hwnd = GetForegroundWindow();
        return (hwnd && ShowWindow(hwnd, SW_MINIMIZE)) ? Action::Minimised : Action::Failed;
    }
    case Policy::Terminate:
        return terminatePid(win.pid) ? Action::ForceClosed : Action::Failed;
    case Policy::Close: {
        if (pendingPid_ == win.pid) {
            // Asked politely already. Still in front after the grace period? Force it.
            if (secondsBetween(pendingSince_, now) < graceSec_) return Action::None;
            pendingPid_ = 0;
            return terminatePid(win.pid) ? Action::ForceClosed : Action::Failed;
        }
        CloseCtx ctx{win.pid, 0};
        EnumWindows(closeWindowsOf, reinterpret_cast<LPARAM>(&ctx));
        pendingPid_   = win.pid;
        pendingSince_ = now;
        return ctx.sent ? Action::Closed : Action::Failed;
    }
    }
    return Action::None;
#else
    (void)now;
    return Action::None;
#endif
}

} // namespace ft

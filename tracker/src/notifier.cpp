#include "notifier.h"

#include <chrono>

#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#include <cwchar>
#endif

namespace ft {

#ifdef _WIN32
namespace {

constexpr UINT kMsgShow = WM_APP + 1;     // "there is something in pending_"
constexpr UINT kMsgQuit = WM_APP + 2;
constexpr UINT kIconId  = 1;

std::wstring widen(const std::string& s) {
    if (s.empty()) return {};
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring out(static_cast<std::size_t>(n), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), n);
    return out;
}

void copyTrunc(wchar_t* dst, std::size_t cap, const std::wstring& src) {
    wcsncpy_s(dst, cap, src.c_str(), _TRUNCATE);
}

Notifier* g_owner = nullptr;   // one notifier per process

} // namespace

static LRESULT CALLBACK notifierWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);

void Notifier::start(const std::string& tooltip) {
    if (thread_.joinable()) return;
    g_owner = this;
    thread_ = std::thread(&Notifier::run, this, tooltip);
    // Wait (briefly) until the window exists, so early notify() calls aren't lost.
    for (int i = 0; i < 100 && !ready_; ++i) std::this_thread::sleep_for(std::chrono::milliseconds(10));
}

void Notifier::run(std::string tooltip) {
    HINSTANCE inst = GetModuleHandleW(nullptr);
    WNDCLASSEXW wc{};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = notifierWndProc;
    wc.hInstance = inst;
    wc.lpszClassName = L"FocusOsNotifier";
    RegisterClassExW(&wc);

    // A hidden window: it never appears, it only owns the tray icon and the queue.
    HWND hwnd = CreateWindowExW(0, wc.lpszClassName, L"FocusOs", WS_OVERLAPPED,
                                0, 0, 0, 0, nullptr, nullptr, inst, nullptr);
    if (!hwnd) { ready_ = true; return; }

    NOTIFYICONDATAW nid{};
    nid.cbSize = sizeof(nid);
    nid.hWnd = hwnd;
    nid.uID = kIconId;
    nid.uFlags = NIF_ICON | NIF_TIP;
    nid.hIcon = LoadIconW(nullptr, MAKEINTRESOURCEW(32516));   // IDI_INFORMATION
    copyTrunc(nid.szTip, ARRAYSIZE(nid.szTip), widen(tooltip));
    Shell_NotifyIconW(NIM_ADD, &nid);
    nid.uVersion = NOTIFYICON_VERSION_4;
    Shell_NotifyIconW(NIM_SETVERSION, &nid);

    hwnd_ = hwnd;
    ready_ = true;

    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {   // blocks in the kernel until a message arrives
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    Shell_NotifyIconW(NIM_DELETE, &nid);
    DestroyWindow(hwnd);
    UnregisterClassW(wc.lpszClassName, inst);
    hwnd_ = nullptr;
}

void Notifier::showPending(void* hwndPtr) {
    // Show the newest pending message (a newer one replaces an older one anyway).
    std::pair<std::string, std::string> item;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (pending_.empty()) return;
        item = pending_.back();
        pending_.clear();
    }
    NOTIFYICONDATAW nid{};
    nid.cbSize = sizeof(nid);
    nid.hWnd = static_cast<HWND>(hwndPtr);
    nid.uID = kIconId;
    nid.uFlags = NIF_INFO;
    nid.dwInfoFlags = NIIF_INFO;
    copyTrunc(nid.szInfoTitle, ARRAYSIZE(nid.szInfoTitle), widen(item.first));
    copyTrunc(nid.szInfo, ARRAYSIZE(nid.szInfo), widen(item.second));
    Shell_NotifyIconW(NIM_MODIFY, &nid);
}

static LRESULT CALLBACK notifierWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    if (msg == kMsgShow && g_owner) {
        g_owner->showPending(hwnd);
        return 0;
    }
    if (msg == kMsgQuit) {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

void Notifier::notify(const std::string& title, const std::string& text) {
    HWND hwnd = static_cast<HWND>(hwnd_.load());
    if (!hwnd) return;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        pending_.emplace_back(title, text);
    }
    // Wake the notifier thread. PostMessage returns at once, it never waits for the UI.
    PostMessageW(hwnd, kMsgShow, 0, 0);
}

void Notifier::stop() {
    HWND hwnd = static_cast<HWND>(hwnd_.load());
    if (hwnd) PostMessageW(hwnd, kMsgQuit, 0, 0);
    if (thread_.joinable()) thread_.join();
    g_owner = nullptr;
}

#else   // non-Windows stub
void Notifier::start(const std::string&) {}
void Notifier::run(std::string) {}
void Notifier::notify(const std::string&, const std::string&) {}
void Notifier::stop() {}
void Notifier::showPending(void*) {}
#endif

Notifier::~Notifier() { stop(); }

} // namespace ft

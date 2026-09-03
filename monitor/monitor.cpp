#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <atomic>
#include <chrono>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "include/segment.h"

constexpr auto POLL_INTERVAL = std::chrono::seconds(2);

std::atomic<bool> running{true};

struct ActiveWindow {
    HWND hwnd{};
    DWORD process_id{};
    std::string process_name;
    std::string window_title;
};


BOOL WINAPI handleConsoleEvent(DWORD event_type) {
    if (event_type == CTRL_C_EVENT || event_type == CTRL_BREAK_EVENT) {
        running = false;
        return TRUE;
    }

    return FALSE;
}


std::string toUtf8(const std::wstring& text) {
    if (text.empty()) {
        return "";
    }

    int required_size = WideCharToMultiByte(
        CP_UTF8,
        0,
        text.c_str(),
        static_cast<int>(text.size()),
        nullptr,
        0,
        nullptr,
        nullptr
    );

    std::string result(required_size, '\0');

    WideCharToMultiByte(
        CP_UTF8,
        0,
        text.c_str(),
        static_cast<int>(text.size()),
        result.data(),
        required_size,
        nullptr,
        nullptr
    );

    return result;
}


std::string getWindowTitle(HWND hwnd) {
    int length = GetWindowTextLengthW(hwnd);

    if (length <= 0) {
        return "[No window title]";
    }

    std::vector<wchar_t> buffer(length + 1);

    int copied = GetWindowTextW(
        hwnd,
        buffer.data(),
        static_cast<int>(buffer.size())
    );

    return toUtf8(std::wstring(buffer.data(), copied));
}


std::string getProcessName(DWORD process_id) {
    HANDLE process = OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        FALSE,
        process_id
    );

    if (process == nullptr) {
        return "unknown";
    }

    std::vector<wchar_t> path_buffer(1024);
    DWORD size = static_cast<DWORD>(path_buffer.size());

    bool success = QueryFullProcessImageNameW(
        process,
        0,
        path_buffer.data(),
        &size
    );

    CloseHandle(process);

    if (!success) {
        return "unknown";
    }

    std::wstring full_path(path_buffer.data(), size);
    size_t last_slash = full_path.find_last_of(L"\\/");

    std::wstring file_name = (last_slash == std::wstring::npos)
        ? full_path
        : full_path.substr(last_slash + 1);

    return toUtf8(file_name);
}


std::optional<ActiveWindow> getActiveWindow() {
    HWND hwnd = GetForegroundWindow();

    if (hwnd == nullptr) {
        return std::nullopt;
    }

    DWORD process_id = 0;
    GetWindowThreadProcessId(hwnd, &process_id);

    if (process_id == 0) {
        return std::nullopt;
    }

    return ActiveWindow{
        hwnd,
        process_id,
        getProcessName(process_id),
        getWindowTitle(hwnd)
    };
}


bool hasWindowChanged(
    const ActiveWindow& current,
    const ActiveWindow& next
) {
    return current.hwnd != next.hwnd ||
           current.window_title != next.window_title;
}


std::string formatTime(
    const std::chrono::system_clock::time_point& time_point
) {
    std::time_t raw_time = std::chrono::system_clock::to_time_t(time_point);

    std::tm utc_time{};
    gmtime_s(&utc_time, &raw_time);

    std::ostringstream output;
    output << std::put_time(&utc_time, "%Y-%m-%d %H:%M:%S UTC");

    return output.str();
}


Segment createSegment(
    const ActiveWindow& window,
    const std::chrono::system_clock::time_point& start_time,
    const std::chrono::system_clock::time_point& end_time
) {
    Segment segment;

    segment.session_id = 0;  // MySQL will provide this later.
    segment.process_id = window.process_id;
    segment.process_name = window.process_name;
    segment.window_title = window.window_title;
    segment.start_time = start_time;
    segment.end_time = end_time;

    segment.duration_seconds =
        std::chrono::duration_cast<std::chrono::seconds>(
            end_time - start_time
        ).count();

    return segment;
}


void printSegment(const Segment& segment) {
    std::cout << "\n[Completed Segment]\n"
              << "Process:  " << segment.process_name << "\n"
              << "PID:      " << segment.process_id << "\n"
              << "Title:    " << segment.window_title << "\n"
              << "Start:    " << formatTime(segment.start_time) << "\n"
              << "End:      " << formatTime(segment.end_time) << "\n"
              << "Duration: " << segment.duration_seconds << " seconds\n";
}


int main() {
    SetConsoleCtrlHandler(handleConsoleEvent, TRUE);

    std::optional<ActiveWindow> detected_window = getActiveWindow();

    if (!detected_window) {
        std::cerr << "Could not detect an active window.\n";
        return 1;
    }

    ActiveWindow current_window = *detected_window;

    auto segment_start = std::chrono::system_clock::now();

    std::cout << "Focus Tracker monitor started.\n"
              << "Switch applications to create segments.\n"
              << "Press Ctrl+C to stop.\n";

    while (running) {
        std::this_thread::sleep_for(POLL_INTERVAL);

        if (!running) {
            break;
        }

        std::optional<ActiveWindow> detected_next = getActiveWindow();

        if (!detected_next) {
            continue;
        }

        ActiveWindow next_window = *detected_next;

        if (!hasWindowChanged(current_window, next_window)) {
            continue;
        }

        auto segment_end = std::chrono::system_clock::now();

        Segment completed_segment = createSegment(
            current_window,
            segment_start,
            segment_end
        );

        printSegment(completed_segment);

        // Later: push completed_segment into the writer queue here.

        current_window = next_window;
        segment_start = segment_end;
    }

    // Save the final active-window interval before exit.
    auto final_end = std::chrono::system_clock::now();

    Segment final_segment = createSegment(
        current_window,
        segment_start,
        final_end
    );

    printSegment(final_segment);

    std::cout << "\nMonitor stopped safely.\n";
    return 0;
}
#include "process_monitor.h"

#include <algorithm>

#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <string>
#endif

namespace ft {

ProcessMonitor::ProcessMonitor() : ProcessMonitor(Config{}) {}

#ifdef _WIN32

namespace {

std::uint64_t toU64(const FILETIME& ft) {
    return (static_cast<std::uint64_t>(ft.dwHighDateTime) << 32) | ft.dwLowDateTime;
}

std::uint64_t nowFiletime() {
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    return toU64(ft);
}

std::string utf8(const wchar_t* text) {
    int size = WideCharToMultiByte(CP_UTF8, 0, text, -1, nullptr, 0, nullptr, nullptr);
    if (size <= 1) return {};
    std::string out(static_cast<std::size_t>(size - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text, -1, out.data(), size, nullptr, nullptr);
    return out;
}

const char* priorityClassName(DWORD cls) {
    switch (cls) {
    case IDLE_PRIORITY_CLASS:         return "idle";
    case BELOW_NORMAL_PRIORITY_CLASS: return "below_normal";
    case NORMAL_PRIORITY_CLASS:       return "normal";
    case ABOVE_NORMAL_PRIORITY_CLASS: return "above_normal";
    case HIGH_PRIORITY_CLASS:         return "high";
    case REALTIME_PRIORITY_CLASS:     return "realtime";
    default:                          return "unknown";
    }
}

} // namespace

ProcessMonitor::ProcessMonitor(Config cfg) : cfg_(cfg) {
    DWORD n = GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
    cpus_ = n ? static_cast<unsigned>(n) : 1u;
}

std::vector<ProcessSample> ProcessMonitor::sample(std::uint32_t foregroundPid, TimePoint now) {
    std::vector<ProcessSample> out;

    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return out;

    const std::uint64_t wallNow = nowFiletime();
    const double elapsed100ns = haveBaseline_ ? static_cast<double>(wallNow - lastWall100ns_) : 0.0;

    std::unordered_map<std::uint32_t, Previous> current;
    current.reserve(previous_.size() + 16);

    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);

    for (BOOL ok = Process32FirstW(snap, &entry); ok; ok = Process32NextW(snap, &entry)) {
        const std::uint32_t pid = entry.th32ProcessID;
        if (pid == 0) continue;                 // "System Idle Process" is not a real process

        // PROCESS_QUERY_LIMITED_INFORMATION works for most processes without
        // admin rights; protected system processes still refuse and are skipped.
        HANDLE proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
        if (!proc) continue;

        FILETIME created, exited, kernel, user;
        if (!GetProcessTimes(proc, &created, &exited, &kernel, &user)) {
            CloseHandle(proc);
            continue;
        }
        const std::uint64_t cpu = toU64(kernel) + toU64(user);
        const std::uint64_t creation = toU64(created);
        current[pid] = {cpu, creation};

        ProcessSample s;
        s.sampledAt     = now;
        s.pid           = pid;
        s.parentPid     = entry.th32ParentProcessID;
        s.processName   = toLower(utf8(entry.szExeFile));
        s.threadCount   = entry.cntThreads;
        s.basePriority  = static_cast<std::int32_t>(entry.pcPriClassBase);
        s.priorityClass = priorityClassName(GetPriorityClass(proc));
        s.cpuTotalMs    = static_cast<std::int64_t>(cpu / 10000);
        s.isForeground  = (pid == foregroundPid);

        PROCESS_MEMORY_COUNTERS mem{};
        if (GetProcessMemoryInfo(proc, &mem, sizeof(mem))) s.workingSetBytes = mem.WorkingSetSize;
        CloseHandle(proc);

        // Delta only if the same process (same PID *and* creation time) was seen before.
        auto prev = previous_.find(pid);
        if (haveBaseline_ && prev != previous_.end() && prev->second.creationTime == creation &&
            cpu >= prev->second.cpu100ns && elapsed100ns > 0) {
            const std::uint64_t delta = cpu - prev->second.cpu100ns;
            s.cpuDeltaMs = static_cast<std::int64_t>(delta / 10000);
            s.cpuPercent = 100.0 * static_cast<double>(delta) / (elapsed100ns * cpus_);
            out.push_back(std::move(s));
        }
    }
    CloseHandle(snap);

    previous_.swap(current);       // processes that exited simply drop out
    lastWall100ns_ = wallNow;
    if (!haveBaseline_) { haveBaseline_ = true; return {}; }

    // Keep the busiest processes, and always the foreground one.
    std::sort(out.begin(), out.end(),
              [](const ProcessSample& a, const ProcessSample& b) { return a.cpuPercent > b.cpuPercent; });
    std::vector<ProcessSample> kept;
    for (auto& s : out) {
        const bool busy = kept.size() < cfg_.topN && s.cpuPercent >= cfg_.minCpuPercent;
        if (busy || s.isForeground) kept.push_back(std::move(s));
    }
    return kept;
}

#else  // non-Windows stub

ProcessMonitor::ProcessMonitor(Config cfg) : cfg_(cfg) {}
std::vector<ProcessSample> ProcessMonitor::sample(std::uint32_t, TimePoint) { return {}; }

#endif

} // namespace ft

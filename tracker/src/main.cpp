// FocusOs tracker: three threads.
//
//   Thread 1 (main)     window sampler   --+
//                                          +--> BoundedQueue --> Thread 3: DB writer --> PostgreSQL
//   Thread 2            process sampler  --+
//
// Threads 1 and 2 are producers, thread 3 is the single consumer.

#include "async_writer.h"
#include "config.h"
#include "db_client.h"
#include "break_schedule.h"
#include "focus_mode.h"
#include "idle_detector.h"
#include "log.h"
#include "notifier.h"
#include "process_monitor.h"
#include "session_manager.h"
#include "window_monitor.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cctype>
#include <cmath>
#include <csignal>
#include <map>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

#ifdef _WIN32
#include <windows.h>
#endif

namespace {

// ---- state shared between threads -----------------------------------------
// Both are std::atomic, so reading/writing them from different threads is
// data-race free without a mutex.
std::atomic<bool>          g_running{true};
std::atomic<std::uint32_t> g_foregroundPid{0};   // written by thread 1, read by thread 2

#ifndef _WIN32
void onSignal(int) { g_running = false; }
#else
// Windows never sends SIGTERM. Closing the console window, logging off or
// shutting down sends a console control event instead, and the process is
// killed as soon as the handler returns. So we wait (up to ~5 s, the
// Windows limit) until main() has flushed rows and closed the session.
HANDLE g_shutdownDone = nullptr;

BOOL WINAPI onConsoleEvent(DWORD type) {
    switch (type) {
    case CTRL_C_EVENT:
    case CTRL_BREAK_EVENT:
        g_running = false;
        return TRUE;
    case CTRL_CLOSE_EVENT:
    case CTRL_LOGOFF_EVENT:
    case CTRL_SHUTDOWN_EVENT:
        g_running = false;
        if (g_shutdownDone) WaitForSingleObject(g_shutdownDone, 4500);
        return TRUE;
    default:
        return FALSE;
    }
}
#endif

void signalShutdownDone() {
#ifdef _WIN32
    if (g_shutdownDone) SetEvent(g_shutdownDone);
#endif
}

// ---- inter-process control (OS: IPC + mutual exclusion between processes) ---
// Named kernel objects, visible to every process in the user's session:
//   FocusOs.Running  named mutex: only one tracker may run at a time, or every
//                    second would be counted twice. Windows releases it even
//                    if the tracker crashes, so it can never go stale (unlike
//                    a lock file).
//   FocusOs.Stop     named manual-reset event: the dashboard (or
//                    `focus_tracker --stop`) sets it to ask the running
//                    tracker to shut down cleanly.
#ifdef _WIN32
constexpr wchar_t kRunningMutexName[] = L"Local\\FocusOs.Running";
constexpr wchar_t kStopEventName[]    = L"Local\\FocusOs.Stop";
HANDLE g_runningMutex = nullptr;
HANDLE g_stopEvent    = nullptr;
#endif

// Sleep until the time is up, Ctrl+C is pressed, or the stop event is set.
// Waiting on the event blocks in the kernel: no busy polling, and a stop
// request wakes the thread immediately.
void interruptibleSleep(std::chrono::duration<double> d) {
    const auto deadline = std::chrono::steady_clock::now() + d;
    while (g_running && std::chrono::steady_clock::now() < deadline) {
#ifdef _WIN32
        if (g_stopEvent && WaitForSingleObject(g_stopEvent, 50) == WAIT_OBJECT_0) {
            g_running = false;
            break;
        }
        if (!g_stopEvent) std::this_thread::sleep_for(std::chrono::milliseconds(50));
#else
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
#endif
    }
}

// `focus_tracker --stop`: ask a running tracker to stop. Returns an exit code.
int requestStop() {
#ifdef _WIN32
    HANDLE ev = OpenEventW(EVENT_MODIFY_STATE, FALSE, kStopEventName);
    if (!ev) {
        std::cout << "No tracker is running.\n";
        return 1;
    }
    SetEvent(ev);
    CloseHandle(ev);
    std::cout << "Asked the running tracker to stop.\n";
    return 0;
#else
    std::cout << "--stop is only supported on Windows.\n";
    return 1;
#endif
}

// One PC, one user: the tracker always records as user 1.
constexpr std::int64_t kUserId = 1;

struct Options {
    std::string           configPath = "config.ini";
    double                idleSec    = 120.0;
    double                pollSec    = 1.0;
    double                procSec    = 10.0;   // 0 = no process sampling
    double                minutes    = 0.0;    // 0 = run until Ctrl+C
    double                breakEvery = 0.0;    // minutes of focus before each break (0 = no breaks)
    double                breakLen   = 0.0;    // minutes per break
    bool                  focusMode  = false;
    ft::FocusMode::Policy policy     = ft::FocusMode::Policy::Minimise;
    bool                  notify     = true;
    std::set<std::string> extraBlock;
};

// "whatsapp.root.exe" -> "Whatsapp", "discord.exe" -> "Discord"
std::string friendlyAppName(std::string exe) {
    for (const char* suffix : {".exe", ".root"}) {
        const std::string s(suffix);
        if (exe.size() > s.size() && exe.compare(exe.size() - s.size(), s.size(), s) == 0)
            exe.erase(exe.size() - s.size());
    }
    if (!exe.empty()) exe[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(exe[0])));
    return exe;
}

void usage() {
    std::cout <<
        "focus_tracker [options]\n"
        "  --config <path>    INI file with a [database] section (default config.ini)\n"
        "  --idle <sec>       idle threshold in seconds (default 120)\n"
        "  --poll <sec>       window polling interval (default 1)\n"
        "  --proc <sec>       process/CPU snapshot interval (default 10, 0 = off)\n"
        "  --minutes <n>      stop by itself after n minutes, e.g. 25 (default: until Ctrl+C)\n"
        "  --break-every <n>  with --focus: take a break after every n minutes of focus\n"
        "  --break <n>        length of each break in minutes (blocked apps are allowed then)\n"
        "  --focus            enable Focus Mode (block 'distracting' apps)\n"
        "  --block <exe>      extra process to block (repeatable)\n"
        "  --close            close blocked apps (asks first, force-closes if they stay open)\n"
        "  --terminate        force-close blocked apps immediately\n"
        "                     (default with --focus: minimise them)\n"
        "  --no-notify        don't show a Windows notification when an app is blocked\n"
        "  --stop             ask the running tracker to stop cleanly, then exit\n";
}

Options parse(int argc, char** argv) {
    Options o;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) { usage(); std::exit(1); }
            return argv[++i];
        };
        if      (a == "--config")    o.configPath = next();
        else if (a == "--idle")      o.idleSec    = std::stod(next());
        else if (a == "--poll")      o.pollSec    = std::stod(next());
        else if (a == "--proc")      o.procSec    = std::stod(next());
        else if (a == "--minutes")   o.minutes    = std::stod(next());
        else if (a == "--break-every") o.breakEvery = std::stod(next());
        else if (a == "--break")     o.breakLen   = std::stod(next());
        else if (a == "--focus")     o.focusMode  = true;
        else if (a == "--close")     o.policy     = ft::FocusMode::Policy::Close;
        else if (a == "--terminate") o.policy     = ft::FocusMode::Policy::Terminate;
        else if (a == "--no-notify") o.notify     = false;
        else if (a == "--block")     o.extraBlock.insert(next());
        else if (a == "--stop")      std::exit(requestStop());
        else { usage(); std::exit(a == "--help" ? 0 : 1); }
    }
    return o;
}

// Thread 2: process sampler (producer #2). Every procSec seconds it takes a
// snapshot of all processes and queues the busiest ones for the writer.
void processSamplerLoop(ft::IDbClient& sink, std::int64_t sessionId, double procSec) {
    ft::ProcessMonitor monitor;
    ft::logInfo("[proc] sampling every ", procSec, " s on ", monitor.logicalCpus(), " logical CPUs");
    try {
        while (g_running) {
            auto samples = monitor.sample(g_foregroundPid.load(), ft::Clock::now());
            for (auto& s : samples) s.sessionId = sessionId;
            sink.insertProcessSamples(samples);
            interruptibleSleep(std::chrono::duration<double>(procSec));
        }
    } catch (const std::exception& e) {
        ft::logError("[proc] stopped: ", e.what());
    }
}

} // namespace

int main(int argc, char** argv) {
    Options opt = parse(argc, argv);
    if ((opt.breakEvery > 0.0) != (opt.breakLen > 0.0) || opt.breakEvery < 0.0 || opt.breakLen < 0.0) {
        std::cerr << "--break-every and --break go together and must be > 0\n";
        return 1;
    }
    if (opt.pollSec <= 0.0 || opt.idleSec <= 0.0 || opt.procSec < 0.0 || opt.minutes < 0.0) {
        std::cerr << "--poll and --idle must be > 0, --proc and --minutes must be >= 0\n";
        return 1;
    }
#ifdef _WIN32
    // Single instance: if the named mutex already exists, another tracker owns it.
    g_runningMutex = CreateMutexW(nullptr, TRUE, kRunningMutexName);
    if (g_runningMutex && GetLastError() == ERROR_ALREADY_EXISTS) {
        std::cerr << "The tracker is already running. Stop it first (focus_tracker --stop).\n";
        CloseHandle(g_runningMutex);
        return 2;
    }
    // Manual-reset so both the main thread and the process thread see it.
    g_stopEvent = CreateEventW(nullptr, TRUE, FALSE, kStopEventName);
    if (g_stopEvent) ResetEvent(g_stopEvent);

    g_shutdownDone = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    SetConsoleCtrlHandler(onConsoleEvent, TRUE);
    SetConsoleOutputCP(CP_UTF8);   // titles are UTF-8; print them correctly
#else
    std::signal(SIGINT, onSignal);
    std::signal(SIGTERM, onSignal);
#endif

    try {
        bool configFound = false;
        ft::DbConfig dbCfg = ft::loadDbConfig(opt.configPath, configFound);
        if (!configFound)
            std::cout << "No " << opt.configPath << "; using defaults (" << dbCfg.user << "@"
                      << dbCfg.host << ":" << dbCfg.port << "/" << dbCfg.database << ")\n";

        ft::PgDbClient    pg(dbCfg);
        ft::AsyncDbWriter writer(pg, /*queueCapacity=*/64);   // owns thread 3, the consumer
        writer.ensureUser(kUserId, "default");

        std::set<std::string> blocked = opt.extraBlock;
        if (opt.focusMode) {
            auto fromDb = writer.distractingApps(kUserId);
            blocked.insert(fromDb.begin(), fromDb.end());
        }
        ft::FocusMode focus(blocked, opt.policy);

        // Thread 4: notifications ("Discord was closed"), only needed in Focus Mode.
        ft::Notifier notifier;
        if (opt.focusMode && opt.notify) notifier.start("FocusOs: focus mode is on");
        std::map<std::string, ft::TimePoint> lastNotified;   // at most one notification per app per 8 s

        ft::SessionManager::Config cfg;
        cfg.idleThresholdSec = opt.idleSec;
        // The dashboard shows a focus session live, so save more often then.
        if (opt.focusMode) cfg.flushIntervalSec = 5.0;
        ft::SessionManager sm(writer, kUserId, opt.focusMode, cfg);
        sm.start(ft::Clock::now());            // synchronous: we need the session id
        if (opt.minutes > 0.0)                 // still single-threaded here, so safe on pg directly
            pg.setPlannedMinutes(sm.sessionId(), std::max(1, static_cast<int>(std::lround(opt.minutes))));
        if (opt.focusMode && opt.breakEvery > 0.0)
            pg.setBreakPlan(sm.sessionId(), std::max(1, static_cast<int>(std::lround(opt.breakEvery))),
                            std::max(1, static_cast<int>(std::lround(opt.breakLen))));
        writer.start();

        std::thread procThread;
        // RAII: if anything below throws, stop and join thread 2 instead of
        // letting std::thread's destructor call std::terminate.
        struct JoinOnExit {
            std::thread& t;
            ~JoinOnExit() { g_running = false; if (t.joinable()) t.join(); }
        } joinGuard{procThread};

        if (opt.procSec > 0.0)
            procThread = std::thread(processSamplerLoop, std::ref(writer), sm.sessionId(), opt.procSec);

        ft::WindowMonitor monitor;
        ft::IdleDetector  idle;

        ft::logInfo("Session ", sm.sessionId(), " started (", dbCfg.database,
                    ", focus=", (opt.focusMode ? "on" : "off"), "). Ctrl+C to stop.");

        // Thread 1 (main): window sampler, producer #1.
        ft::WindowInfo last;
        const std::chrono::duration<double> period(opt.pollSec);
        const auto deadline = std::chrono::steady_clock::now() +
            std::chrono::duration_cast<std::chrono::steady_clock::duration>(
                std::chrono::duration<double>(opt.minutes * 60.0));

        // Breaks: blocking pauses, and a notification marks the start and the end.
        const ft::BreakSchedule breaks{opt.breakEvery * 60.0, opt.breakLen * 60.0, opt.minutes * 60.0};
        const auto sessionStart = std::chrono::steady_clock::now();
        bool wasOnBreak = false;

        while (g_running) {
            auto now   = ft::Clock::now();
            auto win   = monitor.poll();
            auto idleS = idle.idleSeconds();

            const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - sessionStart).count();
            const bool onBreak = opt.focusMode && breaks.onBreak(elapsed);
            if (onBreak != wasOnBreak) {
                wasOnBreak = onBreak;
                if (onBreak) {
                    const long long mins = std::max(1L, std::lround(breaks.breakLeft(elapsed) / 60.0));
                    ft::logInfo("[focus] break started (", mins, " min)");
                    if (opt.notify) notifier.notify("Break time: " + std::to_string(mins) + " min",
                                                    "Blocked apps are allowed until the break ends.");
                } else {
                    ft::logInfo("[focus] break over");
                    if (opt.notify) notifier.notify("Break over", "Back to focus. Blocked apps are blocked again.");
                }
            }

            const auto action = (opt.focusMode && !onBreak) ? focus.enforce(win, now) : ft::FocusMode::Action::None;
            if (action == ft::FocusMode::Action::Minimised || action == ft::FocusMode::Action::Closed ||
                action == ft::FocusMode::Action::ForceClosed) {
                const char* what = ft::FocusMode::actionName(action);
                ft::logInfo("[focus] ", what, " ", win.processName);
                writer.insertFocusBlock({sm.sessionId(), now, win.processName, what});

                auto seen = lastNotified.find(win.processName);
                if (opt.notify && (seen == lastNotified.end() || ft::secondsBetween(seen->second, now) >= 8.0)) {
                    lastNotified[win.processName] = now;
                    std::string text = "You're in a focus session.";
                    if (opt.minutes > 0.0) {
                        const auto left = std::chrono::duration_cast<std::chrono::minutes>(
                            deadline - std::chrono::steady_clock::now()).count();
                        text = "You're focusing: " + std::to_string(std::max<long long>(left, 0) + 1) + " min left.";
                    }
                    const std::string verb = action == ft::FocusMode::Action::Minimised ? " was minimised" : " was closed";
                    notifier.notify(friendlyAppName(win.processName) + verb, text + " It will be back after your session.");
                }
                win = monitor.poll();   // re-sample after acting
            } else if (action == ft::FocusMode::Action::Failed) {
                ft::logError("[focus] could not stop ", win.processName, " (it may run as administrator)");
            }

            g_foregroundPid.store(win.valid ? win.pid : 0);
            sm.onSample(win, idleS, now);

            if (win != last) {
                ft::logInfo(ft::toIso8601(now), "  ",
                            (win.valid ? win.processName : std::string("<none>")),
                            "  |  ", win.windowTitle);
                last = win;
            }
            interruptibleSleep(period);

            if (opt.minutes > 0.0 && std::chrono::steady_clock::now() >= deadline) {
                ft::logInfo("Time is up (", opt.minutes, " min).");
                g_running = false;   // same shutdown path as Ctrl+C
            }
        }

        // Shutdown order matters: stop the producers first, then let the
        // consumer drain everything that is still queued.
        sm.stop(ft::Clock::now());             // queues the last activity + close-session
        if (procThread.joinable()) procThread.join();
        writer.stop();                         // close queue, drain, join writer thread

        const auto st = writer.stats();
        ft::logInfo("Session ", sm.sessionId(), " closed. Writer: ",
                    st.commandsWritten, " batches written, ", st.commandsDropped, " dropped, ",
                    st.retries, " retries; queue peak ", st.maxQueueDepth, "/", st.queueCapacity,
                    ", producer waits ", st.producerWaits, ".");
    } catch (const std::exception& e) {
        ft::logError("fatal: ", e.what());
        signalShutdownDone();
        return 1;
    }
    signalShutdownDone();
    return 0;
}

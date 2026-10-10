#include "db_client.h"
#include "focus_mode.h"
#include "idle_detector.h"
#include "session_manager.h"
#include "window_monitor.h"

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

namespace {
std::atomic<bool> g_running{true};
void onSignal(int) { g_running = false; }

struct Options {
    std::string           dbPath    = "focus.db";
    std::int64_t          userId    = 1;
    std::string           userName  = "default";
    double                idleSec   = 120.0;
    double                pollSec   = 1.0;
    bool                  focusMode = false;
    bool                  terminate = false;
    std::set<std::string> extraBlock;
};

void usage() {
    std::cout <<
        "focus_tracker [options]\n"
        "  --db <path>        SQLite file (default focus.db)\n"
        "  --user <id>        user id (default 1)\n"
        "  --name <name>      user display name\n"
        "  --idle <sec>       idle threshold in seconds (default 120)\n"
        "  --poll <sec>       polling interval (default 1)\n"
        "  --focus            enable Focus Mode (block 'distracting' apps)\n"
        "  --block <exe>      extra process to block (repeatable)\n"
        "  --terminate        kill blocked apps instead of minimising\n";
}

Options parse(int argc, char** argv) {
    Options o;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) { usage(); std::exit(1); }
            return argv[++i];
        };
        if      (a == "--db")        o.dbPath    = next();
        else if (a == "--user")      o.userId    = std::stoll(next());
        else if (a == "--name")      o.userName  = next();
        else if (a == "--idle")      o.idleSec   = std::stod(next());
        else if (a == "--poll")      o.pollSec   = std::stod(next());
        else if (a == "--focus")     o.focusMode = true;
        else if (a == "--terminate") o.terminate = true;
        else if (a == "--block")     o.extraBlock.insert(next());
        else { usage(); std::exit(a == "--help" ? 0 : 1); }
    }
    return o;
}
} // namespace

int main(int argc, char** argv) {
    Options opt = parse(argc, argv);
    std::signal(SIGINT, onSignal);
    std::signal(SIGTERM, onSignal);

    try {
        ft::SqliteDbClient db(opt.dbPath);
        db.ensureUser(opt.userId, opt.userName);

        std::set<std::string> blocked = opt.extraBlock;
        if (opt.focusMode) {
            auto fromDb = db.distractingApps(opt.userId);
            blocked.insert(fromDb.begin(), fromDb.end());
        }
        ft::FocusMode focus(blocked, opt.terminate);

        ft::SessionManager::Config cfg;
        cfg.idleThresholdSec = opt.idleSec;
        ft::SessionManager sm(db, opt.userId, opt.focusMode, cfg);
        sm.start(ft::Clock::now());

        ft::WindowMonitor monitor;
        ft::IdleDetector  idle;

        std::cout << "Session " << sm.sessionId() << " started (db=" << opt.dbPath
                  << ", focus=" << (opt.focusMode ? "on" : "off") << "). Ctrl+C to stop.\n";

        ft::WindowInfo last;
        const auto period = std::chrono::duration_cast<ft::Clock::duration>(
                                std::chrono::duration<double>(opt.pollSec));

        while (g_running) {
            auto now  = ft::Clock::now();
            auto win  = monitor.poll();
            auto idleS = idle.idleSeconds();

            if (opt.focusMode && focus.enforce(win)) {
                std::cout << "[focus] blocked " << win.processName << "\n";
                win = monitor.poll();   // re-sample after acting
            }

            sm.onSample(win, idleS, now);

            if (win != last) {
                std::cout << ft::toIso8601(now) << "  "
                          << (win.valid ? win.processName : "<none>")
                          << "  |  " << win.windowTitle << "\n";
                last = win;
            }
            std::this_thread::sleep_for(period);
        }

        sm.stop(ft::Clock::now());
        std::cout << "Session " << sm.sessionId() << " closed.\n";
    } catch (const std::exception& e) {
        std::cerr << "fatal: " << e.what() << "\n";
        return 1;
    }
    return 0;
}

#pragma once
// Thread-safe console logging.
//
// std::cout and std::cerr are shared by every thread. Without a lock, two
// threads printing at once interleave their text mid-line (we saw
// "Session [proc] sampling every 2 started ..." in an early test run).
// Printing is therefore a critical section: build the whole line first,
// then write it while holding one mutex.

#include <iostream>
#include <mutex>
#include <sstream>
#include <string>

namespace ft {

inline std::mutex& logMutex() {
    static std::mutex m;   // function-local static: thread-safe initialisation (C++11)
    return m;
}

template <typename... Parts>
void logLine(std::ostream& out, const Parts&... parts) {
    std::ostringstream line;
    (line << ... << parts);                 // build the line outside the lock
    line << '\n';
    std::lock_guard<std::mutex> lock(logMutex());
    out << line.str() << std::flush;        // one write while holding the lock
}

template <typename... Parts> void logInfo(const Parts&... parts)  { logLine(std::cout, parts...); }
template <typename... Parts> void logError(const Parts&... parts) { logLine(std::cerr, parts...); }

} // namespace ft

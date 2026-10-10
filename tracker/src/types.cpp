#include "types.h"
#include <algorithm>
#include <cctype>
#include <ctime>

namespace ft {

std::string toIso8601(TimePoint tp) {
    std::time_t t = Clock::to_time_t(tp);
    std::tm tm{};
#ifdef _WIN32
    gmtime_s(&tm, &t);
#else
    gmtime_r(&t, &tm);
#endif
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm);
    return buf;
}

double secondsBetween(TimePoint a, TimePoint b) {
    return std::chrono::duration<double>(b - a).count();
}

std::string toLower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}

} // namespace ft

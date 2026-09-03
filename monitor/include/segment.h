#pragma once

#include <chrono>
#include <cstdint>
#include <string>

struct Segment {
    long long session_id = 0;

    std::uint32_t process_id = 0;
    std::string process_name;
    std::string window_title;

    std::chrono::system_clock::time_point start_time;
    std::chrono::system_clock::time_point end_time;

    long long duration_seconds = 0;
};
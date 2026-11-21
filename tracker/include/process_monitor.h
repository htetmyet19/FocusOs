#pragma once
// ProcessMonitor: snapshots all running processes (OS: process management)
// and measures how much CPU time the scheduler gave each one (OS: scheduling).
//
// CPU % for a process between two snapshots:
//
//     (kernel_time + user_time)_now - (kernel_time + user_time)_before
//     ---------------------------------------------------------------- * 100
//                 wall_clock_elapsed * number_of_logical_cpus
//
// i.e. its share of all the CPU capacity that existed in that interval.
// The first call only records a baseline and returns nothing.

#include "types.h"

#include <cstdint>
#include <unordered_map>
#include <vector>

namespace ft {

class ProcessMonitor {
public:
    struct Config {
        std::size_t topN          = 20;   // keep at most this many per snapshot...
        double      minCpuPercent = 0.5;  // ...and only those above this (plus the foreground one)
    };

    ProcessMonitor();
    explicit ProcessMonitor(Config cfg);

    std::vector<ProcessSample> sample(std::uint32_t foregroundPid, TimePoint now);

    unsigned logicalCpus() const { return cpus_; }

private:
    struct Previous {
        std::uint64_t cpu100ns     = 0;   // kernel + user, in 100 ns units (FILETIME)
        std::uint64_t creationTime = 0;   // detects a PID being reused by a new process
    };

    Config                                      cfg_;
    unsigned                                    cpus_ = 1;
    std::unordered_map<std::uint32_t, Previous> previous_;
    std::uint64_t                               lastWall100ns_ = 0;
    bool                                        haveBaseline_  = false;
};

} // namespace ft

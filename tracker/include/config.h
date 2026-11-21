#pragma once
// Reads the [database] section of an INI file into a DbConfig:
//
//   [database]
//   host = localhost
//   port = 5432
//   user = focus_user
//   database = study_tracker
//   ; password = ...   (optional; leave it out to use pgpass.conf)
//
// A missing file is not an error: the defaults in DbConfig are used.

#include "db_client.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <stdexcept>
#include <string>

namespace ft {

inline std::string trimCopy(const std::string& s) {
    auto notSpace = [](unsigned char c) { return !std::isspace(c); };
    auto b = std::find_if(s.begin(), s.end(), notSpace);
    auto e = std::find_if(s.rbegin(), s.rend(), notSpace).base();
    return b < e ? std::string(b, e) : std::string();
}

inline DbConfig loadDbConfig(const std::string& path, bool& found) {
    DbConfig cfg;
    std::ifstream file(path);
    found = static_cast<bool>(file);
    if (!found) return cfg;

    std::string line, section;
    while (std::getline(file, line)) {
        line = trimCopy(line);
        if (line.empty() || line[0] == '#' || line[0] == ';') continue;
        if (line.front() == '[' && line.back() == ']') {
            section = trimCopy(line.substr(1, line.size() - 2));
            continue;
        }
        auto eq = line.find('=');
        if (eq == std::string::npos || section != "database") continue;

        const std::string key = trimCopy(line.substr(0, eq));
        const std::string val = trimCopy(line.substr(eq + 1));

        if      (key == "host")     cfg.host = val;
        else if (key == "user")     cfg.user = val;
        else if (key == "password") cfg.password = val;
        else if (key == "database") cfg.database = val;
        else if (key == "port") {
            unsigned long port = std::stoul(val);
            if (port == 0 || port > 65535) throw std::runtime_error("database.port must be 1-65535");
            cfg.port = static_cast<unsigned int>(port);
        }
    }
    return cfg;
}

} // namespace ft

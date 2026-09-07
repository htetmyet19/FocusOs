#pragma once

#include <algorithm>
#include <cctype>
#include <chrono>
#include <fstream>
#include <stdexcept>
#include <string>
#include <unordered_map>

#include "db_client.h"

struct AppConfig {
    DbClient::Config database;
    std::chrono::seconds poll_interval{2};
};

namespace config_detail {

inline std::string trim(std::string text) {
    auto is_space = [](unsigned char character) {
        return std::isspace(character) != 0;
    };

    text.erase(
        text.begin(),
        std::find_if_not(text.begin(), text.end(), is_space)
    );

    text.erase(
        std::find_if_not(text.rbegin(), text.rend(), is_space).base(),
        text.end()
    );

    return text;
}

inline std::string requiredValue(
    const std::unordered_map<std::string, std::string>& values,
    const std::string& key
) {
    auto found = values.find(key);

    if (found == values.end() || found->second.empty()) {
        throw std::runtime_error(
            "Missing required configuration value: " + key
        );
    }

    return found->second;
}

} // namespace config_detail


inline AppConfig loadConfig(const std::string& file_name = "config.ini") {
    std::ifstream file(file_name);

    if (!file) {
        throw std::runtime_error(
            "Could not open configuration file: " + file_name
        );
    }

    std::unordered_map<std::string, std::string> values;

    std::string section;
    std::string line;

    while (std::getline(file, line)) {
        line = config_detail::trim(line);

        if (line.empty() || line[0] == '#' || line[0] == ';') {
            continue;
        }

        if (line.front() == '[' && line.back() == ']') {
            section = config_detail::trim(
                line.substr(1, line.size() - 2)
            );
            continue;
        }

        std::size_t equals_position = line.find('=');

        if (equals_position == std::string::npos || section.empty()) {
            continue;
        }

        std::string key = config_detail::trim(
            line.substr(0, equals_position)
        );

        std::string value = config_detail::trim(
            line.substr(equals_position + 1)
        );

        values[section + "." + key] = value;
    }

    AppConfig config;

    config.database.host =
        config_detail::requiredValue(values, "database.host");

    config.database.port = static_cast<unsigned int>(
        std::stoul(
            config_detail::requiredValue(values, "database.port")
        )
    );

    if (config.database.port == 0 || config.database.port > 65535) {
        throw std::runtime_error("database.port must be between 1 and 65535.");
    }

    config.database.user =
        config_detail::requiredValue(values, "database.user");

    config.database.password =
        config_detail::requiredValue(values, "database.password");

    config.database.database =
        config_detail::requiredValue(values, "database.database");

    unsigned long poll_seconds = std::stoul(
        config_detail::requiredValue(values, "monitor.poll_seconds")
    );

    if (poll_seconds == 0) {
        throw std::runtime_error("monitor.poll_seconds must be greater than 0.");
    }

    config.poll_interval = std::chrono::seconds(poll_seconds);

    return config;
}
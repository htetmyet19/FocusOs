#pragma once

#include <algorithm>
#include <cctype>
#include <string>
#include <unordered_set>

namespace category_rules {

inline std::string toLower(std::string text) {
    std::transform(
        text.begin(),
        text.end(),
        text.begin(),
        [](unsigned char character) {
            return static_cast<char>(std::tolower(character));
        }
    );

    return text;
}

inline std::string classifyProcess(const std::string& process_name) {
    static const std::unordered_set<std::string> productive = {
        "code.exe",
        "chatgpt.exe",
        "winword.exe",
        "excel.exe",
        "powerpnt.exe",
        "notepad.exe",
        "acrord32.exe"
    };

    static const std::unordered_set<std::string> distracting = {
        "discord.exe",
        "steam.exe",
        "spotify.exe"
    };

    const std::string normalized_name = toLower(process_name);

    if (productive.count(normalized_name) > 0) {
        return "Productive";
    }

    if (distracting.count(normalized_name) > 0) {
        return "Distracting";
    }

    return "Neutral";
}

} // namespace category_rules
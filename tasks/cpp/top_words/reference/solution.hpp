#pragma once
#include <algorithm>
#include <cstddef>
#include <map>
#include <string>
#include <utility>
#include <vector>

// The n most frequent lowercase ASCII-letter words with their counts, ties ordered alphabetically.
inline std::vector<std::pair<std::string, int>> top_words(const std::string& text, std::size_t n) {
    std::map<std::string, int> counts;
    std::string word;
    for (std::size_t i = 0; i <= text.size(); i++) {
        char c = i < text.size() ? text[i] : ' ';
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')) {
            word += static_cast<char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);
        } else if (!word.empty()) {
            counts[word]++;
            word.clear();
        }
    }
    std::vector<std::pair<std::string, int>> ranked(counts.begin(), counts.end());
    std::stable_sort(ranked.begin(), ranked.end(),
                     [](const auto& a, const auto& b) { return a.second > b.second; });
    if (ranked.size() > n) ranked.resize(n);
    return ranked;
}

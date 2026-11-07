Write a C++17 header solution.hpp (no main) with:

```cpp
std::vector<std::pair<std::string, int>> top_words(const std::string& text, std::size_t n);
```

Words are maximal runs of ASCII letters (A-Z, a-z). Count them case-insensitively and return them in lowercase. Return the n most frequent words with their counts, most frequent first; words with equal counts are ordered alphabetically. If there are fewer than n distinct words, return all of them.

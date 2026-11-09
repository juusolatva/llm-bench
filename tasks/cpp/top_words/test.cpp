#include <cstdio>
#include <string>
#include <utility>
#include <vector>
#include "solution.hpp"

using harness_vec = std::vector<std::pair<std::string, int>>;
static int harness_fails;
static void harness_t(const std::string& text, std::size_t n, const harness_vec& want) {
    auto got = top_words(text, n);
    if (got != want) {
        std::fprintf(stderr, "top_words(\"%s\", %zu): got", text.c_str(), n);
        for (auto& p : got) std::fprintf(stderr, " %s:%d", p.first.c_str(), p.second);
        std::fprintf(stderr, " | want");
        for (auto& p : want) std::fprintf(stderr, " %s:%d", p.first.c_str(), p.second);
        std::fprintf(stderr, "\n");
        harness_fails++;
    }
}
int main() {
    const std::string s = "The cat and the hat. THE end, cat!";
    harness_t(s, 3, {{"the", 3}, {"cat", 2}, {"and", 1}});
    harness_t(s, 10, {{"the", 3}, {"cat", 2}, {"and", 1}, {"end", 1}, {"hat", 1}});
    harness_t(s, 0, {});
    harness_t("", 5, {});
    harness_t("it's a1b a", 5, {{"a", 2}, {"b", 1}, {"it", 1}, {"s", 1}});
    harness_t("zeta Alpha alpha ZETA beta", 2, {{"alpha", 2}, {"zeta", 2}});
    if (harness_fails) return 1;
    std::puts("harness: all checks passed");
}

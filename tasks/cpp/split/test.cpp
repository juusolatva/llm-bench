#include <cstdio>
#include <string>
#include <vector>
#include "solution.hpp"

static int harness_fails;
static void harness_t(const std::string& s, char d, const std::vector<std::string>& want) {
    auto got = split(s, d);
    if (got != want) {
        std::fprintf(stderr, "split(\"%s\", '%c') returned %zu fields:", s.c_str(), d, got.size());
        for (auto& g : got) std::fprintf(stderr, " [%s]", g.c_str());
        std::fprintf(stderr, ", want %zu\n", want.size());
        harness_fails++;
    }
}
int main() {
    harness_t("a,b,c", ',', {"a", "b", "c"});
    harness_t("a,,b", ',', {"a", "", "b"});
    harness_t("", ',', {""});
    harness_t(",", ',', {"", ""});
    harness_t(",a,", ',', {"", "a", ""});
    harness_t("abc", ',', {"abc"});
    harness_t("a b  c", ' ', {"a", "b", "", "c"});
    if (harness_fails) return 1;
    std::puts("ok");
}

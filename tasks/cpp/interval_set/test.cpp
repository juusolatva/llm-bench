#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <utility>
#include <vector>
#include "solution.hpp"

using harness_vec = std::vector<std::pair<long, long>>;
static int harness_fails;

static std::string harness_str(const harness_vec& v) {
    std::string s = "{";
    for (auto& p : v) s += " [" + std::to_string(p.first) + "," + std::to_string(p.second) + ")";
    return s + " }";
}
static void harness_expect(const IntervalSet& s, const harness_vec& want, const char* after) {
    auto got = s.intervals();
    if (got != want) {
        std::fprintf(stderr, "after %s: intervals() = %s, want %s\n", after, harness_str(got).c_str(),
                     harness_str(want).c_str());
        harness_fails++;
    }
}
#define HARNESS_CHECK(c, msg) do { if (!(c)) { std::fprintf(stderr, "FAIL: %s\n", msg); harness_fails++; } } while (0)

int main() {
    IntervalSet s;
    harness_expect(s, {}, "construction");
    HARNESS_CHECK(!s.contains(0), "empty set contains 0");
    s.add(5, 5);
    s.add(7, 3);
    harness_expect(s, {}, "add(5, 5), add(7, 3)");
    s.add(1, 3);
    s.add(3, 5);
    harness_expect(s, {{1, 5}}, "add(1, 3), add(3, 5)");
    s.add(10, 20);
    s.add(-5, -2);
    harness_expect(s, {{-5, -2}, {1, 5}, {10, 20}}, "add(10, 20), add(-5, -2)");
    HARNESS_CHECK(s.contains(-5) && s.contains(4) && s.contains(19), "contains inside intervals");
    HARNESS_CHECK(!s.contains(-2) && !s.contains(5) && !s.contains(20) && !s.contains(0), "contains outside intervals");
    s.add(4, 11);
    harness_expect(s, {{-5, -2}, {1, 20}}, "add(4, 11)");
    s.add(2, 8);
    harness_expect(s, {{-5, -2}, {1, 20}}, "add(2, 8) inside an interval");
    s.remove(5, 7);
    harness_expect(s, {{-5, -2}, {1, 5}, {7, 20}}, "remove(5, 7)");
    s.remove(-10, 2);
    harness_expect(s, {{2, 5}, {7, 20}}, "remove(-10, 2)");
    s.remove(4, 8);
    harness_expect(s, {{2, 4}, {8, 20}}, "remove(4, 8)");
    s.remove(30, 40);
    s.remove(9, 9);
    harness_expect(s, {{2, 4}, {8, 20}}, "remove(30, 40), remove(9, 9)");
    s.remove(8, 20);
    harness_expect(s, {{2, 4}}, "remove(8, 20)");
    s.add(-3, 100);
    s.remove(-100, 200);
    harness_expect(s, {}, "add(-3, 100), remove(-100, 200)");
    s.add(0, 10);
    s.remove(3, 4);
    s.add(3, 4);
    harness_expect(s, {{0, 10}}, "remove(3, 4) then add(3, 4)");

    auto t0 = std::chrono::steady_clock::now();
    IntervalSet big;
    const long n = 200000;
    for (long i = 0; i < n; i++) big.add(3 * i, 3 * i + 1);
    for (long i = 0; i < n; i++)
        HARNESS_CHECK(big.contains(3 * i) && !big.contains(3 * i + 1), "contains in a large set");
    for (long i = 0; i < n; i += 2) big.remove(3 * i, 3 * i + 1);
    for (long i = 1; i + 1 < n; i += 4) big.add(3 * i, 3 * i + 7);
    auto iv = big.intervals();
    HARNESS_CHECK(iv.size() == static_cast<std::size_t>(n / 4), "interval count in a large set");
    HARNESS_CHECK(!iv.empty() && iv[0] == std::make_pair(3L, 10L), "first interval in a large set");
    double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    HARNESS_CHECK(secs < 20, "too slow: operations are not O(log n)");
    if (harness_fails) return 1;
    std::puts("ok");
}

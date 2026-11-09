#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <utility>
#include <vector>
#include "solution.hpp"

using harness_vec = std::vector<std::pair<long, long>>;
static int harness_fails;

// Format intervals as "{ [lo,hi) ... }".
static std::string harness_str(const harness_vec& v) {
    std::string s = "{";
    for (auto& p : v) s += " [" + std::to_string(p.first) + "," + std::to_string(p.second) + ")";
    return s + " }";
}
// Check s.intervals() against want after the operations described by `after`.
static void harness_expect(const IntervalSet& s, const harness_vec& want, const char* after) {
    auto got = s.intervals();
    if (got != want) {
        std::fprintf(stderr, "after %s: intervals() = %s, want %s\n", after, harness_str(got).c_str(),
                     harness_str(want).c_str());
        harness_fails++;
    }
}
// Check s.contains(x) against want.
static void harness_contains(const IntervalSet& s, long x, bool want, const char* after) {
    if (s.contains(x) != want) {
        std::fprintf(stderr, "after %s: contains(%ld) = %s, want %s (intervals() = %s)\n", after, x,
                     want ? "false" : "true", want ? "true" : "false", harness_str(s.intervals()).c_str());
        harness_fails++;
    }
}

// The large-set test: called after each call, so a slow solution fails as soon as the test has taken 20 s, well
// before the sandbox's time limit. `call` is the call that just returned, with i its loop index (-1: none).
static std::chrono::steady_clock::time_point harness_t0;
static void harness_check_time(const char* call, long i) {
    double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - harness_t0).count();
    if (secs < 20) return;
    char where[64] = "";
    if (i >= 0) std::snprintf(where, sizeof where, " with i = %ld", i);
    std::fprintf(stderr, "too slow: the large-set test (add(3i, 3i+1) for i = 0..199999; then contains(3i) and "
                 "contains(3i+1) for each i; then remove(3i, 3i+1) for even i; then add(3i, 3i+7) for i = 1, 5, 9, ...; "
                 "then intervals()) has taken %.1f s (limit 20 s) and the last call to return was %s%s; contains must "
                 "run in O(log n), and add and remove in O(log n) plus O(1) per stored interval they merge or delete\n",
                 secs, call, where);
    std::exit(1);
}

int main() {
    IntervalSet s;
    harness_expect(s, {}, "construction");
    harness_contains(s, 0, false, "construction");
    s.add(5, 5);
    s.add(7, 3);
    harness_expect(s, {}, "add(5, 5), add(7, 3)");
    s.add(1, 3);
    s.add(3, 5);
    harness_expect(s, {{1, 5}}, "add(1, 3), add(3, 5)");
    s.add(10, 20);
    s.add(-5, -2);
    harness_expect(s, {{-5, -2}, {1, 5}, {10, 20}}, "add(10, 20), add(-5, -2)");
    for (long x : {-5L, -3L, 1L, 4L, 10L, 19L}) harness_contains(s, x, true, "add(10, 20), add(-5, -2)");
    for (long x : {-6L, -2L, 0L, 5L, 9L, 20L}) harness_contains(s, x, false, "add(10, 20), add(-5, -2)");
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

    // Large set: add [3i, 3i+1) for i < 200000, remove the even i, then add [3i, 3i+7) for i = 1, 5, 9, ...
    // which merges each with the interval starting at 3(i+2). Expected: n/4 intervals [3i, 3i+7).
    harness_t0 = std::chrono::steady_clock::now();
    IntervalSet big;
    const long n = 200000;
    for (long i = 0; i < n; i++) {
        big.add(3 * i, 3 * i + 1);
        harness_check_time("add(3i, 3i+1)", i);
    }
    for (long i = 0; i < n; i++) {
        bool in = big.contains(3 * i);
        harness_check_time("contains(3i)", i);
        bool after = big.contains(3 * i + 1);
        harness_check_time("contains(3i+1)", i);
        if (!in || after) {
            std::fprintf(stderr, "large set after adding [3i, 3i+1) for i < %ld: contains(%ld) = %d, contains(%ld) = %d, "
                         "want 1 and 0\n", n, 3 * i, in, 3 * i + 1, after);
            return 1;
        }
    }
    for (long i = 0; i < n; i += 2) {
        big.remove(3 * i, 3 * i + 1);
        harness_check_time("remove(3i, 3i+1)", i);
    }
    for (long i = 1; i + 1 < n; i += 4) {
        big.add(3 * i, 3 * i + 7);
        harness_check_time("add(3i, 3i+7)", i);
    }
    auto iv = big.intervals();
    harness_check_time("intervals()", -1);
    harness_vec head(iv.begin(), iv.begin() + std::min<std::size_t>(iv.size(), 3));
    if (iv.size() != static_cast<std::size_t>(n / 4) || head != harness_vec{{3, 10}, {15, 22}, {27, 34}}) {
        std::fprintf(stderr, "large set: intervals() has %zu intervals starting %s, want %ld starting { [3,10) [15,22) [27,34) }\n",
                     iv.size(), harness_str(head).c_str(), n / 4);
        harness_fails++;
    }
    if (harness_fails) return 1;
    std::puts("ok");
}

#include "solution.hpp"
#include <algorithm>
#include <chrono>
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <utility>
#include <vector>

using harness_vec = std::vector<std::pair<long, long>>;
static int harness_fails;

// Format intervals as "{ [lo,hi) ... }".
static std::string harness_str(const harness_vec& v) {
    std::string s = "{";
    for (auto& p : v) s += " [" + std::to_string(p.first) + "," + std::to_string(p.second) + ")";
    return s + " }";
}
// Runs calls on one IntervalSet s and records them, so a failure can show every call made so far. Stops at the
// first failure: later checks would depend on a state the solution got wrong.
struct harness_set {
    IntervalSet s;
    std::string log = "IntervalSet s";
    void fail(const std::string& what) {
        std::fprintf(stderr, "FAIL: after %s: %s\n", log.c_str(), what.c_str());
        std::exit(1);
    }
    void add(long lo, long hi) {
        s.add(lo, hi);
        log += ", s.add(" + std::to_string(lo) + ", " + std::to_string(hi) + ")";
    }
    void remove(long lo, long hi) {
        s.remove(lo, hi);
        log += ", s.remove(" + std::to_string(lo) + ", " + std::to_string(hi) + ")";
    }
    void expect(const harness_vec& want) {
        auto got = std::as_const(s).intervals();
        if (got != want) fail("s.intervals() = " + harness_str(got) + ", want " + harness_str(want));
    }
    void contains(long x, bool want) {
        if (std::as_const(s).contains(x) != want)
            fail("s.contains(" + std::to_string(x) + ") = " + (want ? "false" : "true") + ", want " +
                 (want ? "true" : "false") + " (s.intervals() = " + harness_str(s.intervals()) + ")");
    }
};

// The large-set test: called after each call, so a slow solution fails as soon as the test has taken 20 s, well
// before the sandbox's time limit. `call` is the call that just returned, with i its loop index (-1: none).
static std::chrono::steady_clock::time_point harness_t0;
static void harness_check_time(const char* call, long i) {
    double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - harness_t0).count();
    if (secs < 20) return;
    char where[64] = "";
    if (i >= 0) std::snprintf(where, sizeof where, " with i = %ld", i);
    std::fprintf(stderr, "too slow: the large-set test (add(3i, 3i+1) for i = 399999 down to 0; then contains(3i) and "
                 "contains(3i+1) for each i; then remove(3i, 3i+1) for even i; then add(3i, 3i+7) for i = 1, 5, 9, ...; "
                 "then intervals()) has taken %.1f s (limit 20 s) and the last call to return was %s%s; contains must "
                 "run in O(log n), and add and remove in O(log n) plus O(1) per stored interval they merge or delete\n",
                 secs, call, where);
    std::exit(1);
}

int main() {
    harness_set h;
    h.expect({});
    h.contains(0, false);
    h.add(5, 5);
    h.add(7, 3);
    h.expect({});
    h.add(1, 3);
    h.add(3, 5);
    h.expect({{1, 5}});
    h.add(10, 20);
    h.add(-5, -2);
    h.expect({{-5, -2}, {1, 5}, {10, 20}});
    for (long x : {-5L, -3L, 1L, 4L, 10L, 19L}) h.contains(x, true);
    for (long x : {-6L, -2L, 0L, 5L, 9L, 20L}) h.contains(x, false);
    h.add(4, 11);
    h.expect({{-5, -2}, {1, 20}});
    h.add(2, 8);                                       // inside an interval
    h.expect({{-5, -2}, {1, 20}});
    h.remove(5, 7);
    h.expect({{-5, -2}, {1, 5}, {7, 20}});
    h.remove(-10, 2);
    h.expect({{2, 5}, {7, 20}});
    h.remove(4, 8);
    h.expect({{2, 4}, {8, 20}});
    h.remove(30, 40);
    h.remove(9, 9);
    h.expect({{2, 4}, {8, 20}});
    h.remove(15, 10);                                  // lo > hi inside an interval: nothing happens
    h.expect({{2, 4}, {8, 20}});
    h.contains(12, true);
    h.remove(8, 20);
    h.expect({{2, 4}});
    h.add(-3, 100);
    h.remove(-100, 200);
    h.expect({});
    h.add(0, 10);
    h.remove(3, 4);
    h.add(3, 4);
    h.expect({{0, 10}});
    h.add(LONG_MIN, -(1L << 40));                      // endpoints beyond 32 bits, up to the limits of long
    h.add(1L << 40, LONG_MAX);
    h.expect({{LONG_MIN, -(1L << 40)}, {0, 10}, {1L << 40, LONG_MAX}});
    h.contains(LONG_MIN, true);
    h.contains(-(1L << 40), false);
    h.contains(LONG_MAX - 1, true);
    h.contains(LONG_MAX, false);
    h.remove(LONG_MIN, LONG_MAX);
    h.expect({});

    // Large set: add [3i, 3i+1) for i < 400000 in descending order (each one in front of all the others), remove
    // the even i, then add [3i, 3i+7) for i = 1, 5, 9, ... which merges each with the interval starting at 3(i+2).
    // Expected: n/4 intervals [3i, 3i+7).
    harness_t0 = std::chrono::steady_clock::now();
    IntervalSet big;
    const long n = 400000;
    for (long i = n - 1; i >= 0; i--) {
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
    auto iv = std::as_const(big).intervals();
    harness_check_time("intervals()", -1);
    harness_vec head(iv.begin(), iv.begin() + std::min<std::size_t>(iv.size(), 3));
    if (iv.size() != static_cast<std::size_t>(n / 4) || head != harness_vec{{3, 10}, {15, 22}, {27, 34}}) {
        std::fprintf(stderr, "large set: intervals() has %zu intervals starting %s, want %ld starting { [3,10) [15,22) [27,34) }\n",
                     iv.size(), harness_str(head).c_str(), n / 4);
        harness_fails++;
    } else {
        for (std::size_t k = 0; k < iv.size(); k++) {
            long i = 4 * static_cast<long>(k) + 1;
            if (iv[k] != std::pair<long, long>{3 * i, 3 * i + 7}) {
                std::fprintf(stderr, "large set: intervals()[%zu] = [%ld,%ld), want [%ld,%ld) (the intervals are [3i, 3i+7) "
                             "for i = 1, 5, 9, ...)\n", k, iv[k].first, iv[k].second, 3 * i, 3 * i + 7);
                harness_fails++;
                break;
            }
        }
    }
    if (harness_fails) return 1;
    std::puts("harness: all checks passed");
}

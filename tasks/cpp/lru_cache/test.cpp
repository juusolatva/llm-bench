#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <optional>
#include <string>
#include "solution.hpp"

static std::string harness_text(const std::string& s) { return "\"" + s + "\""; }
static std::string harness_text(int x) { return std::to_string(x); }
static std::string harness_text(const std::optional<int>& o) { return o ? std::to_string(*o) : "std::nullopt"; }

// Runs calls on an LruCache<K, int> and records them, so a failure can show every call made so far.
template <typename K>
struct HarnessCache {
    LruCache<K, int> cache;
    std::string log;
    explicit HarnessCache(std::size_t capacity) : cache(capacity), log("LruCache(" + std::to_string(capacity) + ")") {}
    void fail(const std::string& what) {
        std::fprintf(stderr, "FAIL: after %s: %s\n", log.c_str(), what.c_str());
        std::exit(1);
    }
    void put(const K& key, int value) {
        cache.put(key, value);
        log += ", put(" + harness_text(key) + ", " + std::to_string(value) + ")";
    }
    void get(const K& key, std::optional<int> want) {
        std::optional<int> got = cache.get(key);
        if (got != want)
            fail("get(" + harness_text(key) + ") returned " + harness_text(got) + ", want " + harness_text(want));
        log += ", get(" + harness_text(key) + ")";
    }
    void size(std::size_t want) {
        std::size_t got = cache.size();
        if (got != want) fail("size() returned " + std::to_string(got) + ", want " + std::to_string(want));
        log += ", size()";
    }
};

int main() {
    HarnessCache<std::string> c(2);
    c.size(0);
    c.get("a", std::nullopt);
    c.put("a", 1);
    c.put("b", 2);
    c.get("a", 1);                                     // a is now most recent
    c.put("c", 3);                                     // evicts b
    c.get("b", std::nullopt);
    c.get("a", 1);
    c.get("c", 3);
    c.put("a", 10);                                    // update, a most recent
    c.put("d", 4);                                     // evicts c
    c.get("c", std::nullopt);
    c.get("a", 10);
    c.get("d", 4);
    c.size(2);

    HarnessCache<std::string> u(2);
    u.put("a", 1);
    u.put("b", 2);
    u.put("b", 9);                                     // update at capacity: nothing is evicted
    u.get("a", 1);
    u.get("b", 9);
    u.size(2);

    HarnessCache<int> one(1);
    one.put(1, 1);
    one.put(2, 2);
    one.get(1, std::nullopt);
    one.get(2, 2);
    one.size(1);

    // Timing: put(i, i) for i < n; every third step also get(i - capacity / 2), which is still cached.
    // The elapsed time is checked during the loop, so an O(capacity) get or put fails here quickly.
    const int capacity = 200000, n = 600000;
    const double limit = 15;
    auto t0 = std::chrono::steady_clock::now();
    LruCache<int, int> big(capacity);
    for (int i = 0; i < n; i++) {
        big.put(i, i);
        if (i >= capacity / 2 && i % 3 == 0) {
            std::optional<int> got = big.get(i - capacity / 2);
            if (got != i - capacity / 2) {
                std::fprintf(stderr, "FAIL: LruCache<int, int>(%d), put(i, i) for i = 0, 1, 2, ... and get(i - %d) "
                             "after each put where i >= %d and i %% 3 == 0: at i = %d, get(%d) returned %s, want %d\n",
                             capacity, capacity / 2, capacity / 2, i, i - capacity / 2, harness_text(got).c_str(),
                             i - capacity / 2);
                return 1;
            }
        }
        if (i % 1000 == 999) {
            double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
            if (secs > limit) {
                std::fprintf(stderr, "FAIL: too slow: LruCache<int, int>(%d) took %.1f s (limit %.0f s) for the first "
                             "%d of %d puts and the gets between them; get and put must be O(1) on average\n",
                             capacity, secs, limit, i + 1, n);
                return 1;
            }
        }
    }
    if (big.size() != std::size_t(capacity)) {
        std::fprintf(stderr, "FAIL: LruCache<int, int>(%d) after %d puts of distinct keys: size() returned %zu, "
                     "want %d\n", capacity, n, big.size(), capacity);
        return 1;
    }
    std::puts("ok");
}

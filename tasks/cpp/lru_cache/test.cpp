#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <optional>
#include <string>
#include "solution.hpp"

#define HARNESS_CHECK(c, msg) do { if (!(c)) { std::fprintf(stderr, "FAIL: %s\n", msg); std::exit(1); } } while (0)

int main() {
    LruCache<std::string, int> c(2);
    HARNESS_CHECK(c.size() == 0 && !c.get("a"), "empty cache");
    c.put("a", 1);
    c.put("b", 2);
    HARNESS_CHECK(c.get("a") == 1, "get a");          // a is now most recent
    c.put("c", 3);                                     // evicts b
    HARNESS_CHECK(!c.get("b"), "b should have been evicted");
    HARNESS_CHECK(c.get("a") == 1 && c.get("c") == 3, "a and c present");
    c.put("a", 10);                                    // update, a most recent
    c.put("d", 4);                                     // evicts c
    HARNESS_CHECK(!c.get("c"), "c should have been evicted");
    HARNESS_CHECK(c.get("a") == 10 && c.get("d") == 4, "updated a and d present");
    HARNESS_CHECK(c.size() == 2, "size stays at capacity");

    LruCache<int, int> one(1);
    one.put(1, 1); one.put(2, 2);
    HARNESS_CHECK(!one.get(1) && one.get(2) == 2 && one.size() == 1, "capacity 1");

    auto t0 = std::chrono::steady_clock::now();
    LruCache<int, int> big(10000);
    for (int i = 0; i < 300000; i++) {
        big.put(i, i);
        if (i >= 5000 && i % 3 == 0) HARNESS_CHECK(big.get(i - 5000) == i - 5000, "recently inserted key missing");
    }
    double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    HARNESS_CHECK(big.size() == 10000, "size after many puts");
    HARNESS_CHECK(secs < 20, "too slow: get/put not O(1)");
    std::puts("ok");
}

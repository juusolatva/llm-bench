#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>
#include "solution.hpp"

#define HARNESS_CHECK(c, msg) do { if (!(c)) { std::fprintf(stderr, "FAIL: %s\n", msg); std::exit(1); } } while (0)

int main() {
    Buffer a(4);
    HARNESS_CHECK(a.size() == 4 && a[0] == 0 && a[3] == 0, "constructor zero-fills");
    a[0] = 'x';
    {
        Buffer b = a;
        HARNESS_CHECK(b.size() == 4 && b[0] == 'x', "copy has same contents");
        b[0] = 'y';
        HARNESS_CHECK(a[0] == 'x', "copy is not independent");
        HARNESS_CHECK(b.data() != a.data(), "copy shares memory");
    }
    HARNESS_CHECK(a[0] == 'x', "original damaged after copy destroyed");
    {
        Buffer c(2);
        c = a;
        HARNESS_CHECK(c.size() == 4 && c[0] == 'x', "copy assignment contents");
        c[1] = 'z';
        HARNESS_CHECK(a[1] == 0, "copy assignment not independent");
    }
    Buffer& ref = a;
    a = ref;
    HARNESS_CHECK(a.size() == 4 && a[0] == 'x', "self-assignment broke the buffer");

    char* p = a.data();
    Buffer m(std::move(a));
    HARNESS_CHECK(m.data() == p && m.size() == 4, "move constructor must transfer the memory");
    HARNESS_CHECK(a.size() == 0, "moved-from size must be 0");
    Buffer n(1);
    n = std::move(m);
    HARNESS_CHECK(n.data() == p && n.size() == 4 && n[0] == 'x', "move assignment must transfer the memory");
    HARNESS_CHECK(m.size() == 0, "moved-from (assignment) size must be 0");

    std::vector<Buffer> v;
    for (int i = 0; i < 100; i++) { Buffer t(16); t[0] = char(i); v.push_back(t); v.push_back(std::move(t)); }
    for (int i = 0; i < 100; i++) HARNESS_CHECK(v[2 * i][0] == char(i) && v[2 * i + 1][0] == char(i), "vector of buffers");
    std::vector<Buffer> w = v;
    HARNESS_CHECK(w.size() == 200 && w[10][0] == char(5), "copy of vector");
    std::puts("ok");
}

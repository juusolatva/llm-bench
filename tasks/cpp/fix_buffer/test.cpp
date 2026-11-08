#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>
#include "solution.hpp"

#define HARNESS_CHECK(c, ...) do { if (!(c)) { std::fprintf(stderr, "FAIL: " __VA_ARGS__); std::fputc('\n', stderr); std::exit(1); } } while (0)

int main() {
    Buffer a(4);
    HARNESS_CHECK(a.size() == 4 && a[0] == 0 && a[3] == 0,
                  "Buffer a(4): size() = %zu, a[0] = %d, a[3] = %d; want size() 4 and zero-filled", a.size(), a[0], a[3]);
    a[0] = 'x';
    {
        Buffer b = a;
        HARNESS_CHECK(b.size() == 4 && b[0] == 'x',
                      "Buffer b = a (a has size 4, a[0] = 'x'): b.size() = %zu, b[0] = %d; want 4 and 'x' (%d)",
                      b.size(), b[0], 'x');
        b[0] = 'y';
        HARNESS_CHECK(a[0] == 'x', "Buffer b = a; b[0] = 'y': a[0] = %d, want 'x' (%d); copies must be independent",
                      a[0], 'x');
        HARNESS_CHECK(b.data() != a.data(), "Buffer b = a: b.data() == a.data(); a copy must have its own memory");
    }
    HARNESS_CHECK(a[0] == 'x', "after a copy of a was destroyed: a[0] = %d, want 'x' (%d)", a[0], 'x');
    {
        Buffer c(2);
        c = a;
        HARNESS_CHECK(c.size() == 4 && c[0] == 'x',
                      "Buffer c(2); c = a (a has size 4, a[0] = 'x'): c.size() = %zu, c[0] = %d; want 4 and 'x' (%d)",
                      c.size(), c[0], 'x');
        c[1] = 'z';
        HARNESS_CHECK(a[1] == 0, "c = a; c[1] = 'z': a[1] = %d, want 0; copy assignment must make an independent copy",
                      a[1]);
    }
    Buffer& ref = a;
    a = ref;
    HARNESS_CHECK(a.size() == 4 && a[0] == 'x',
                  "self-assignment a = a (a has size 4, a[0] = 'x'): a.size() = %zu, a[0] = %d; want 4 and 'x' (%d)",
                  a.size(), a[0], 'x');

    char* p = a.data();
    Buffer m(std::move(a));
    HARNESS_CHECK(m.data() == p && m.size() == 4,
                  "Buffer m(std::move(a)) (a has size 4): m.size() = %zu, m.data() %s a's old data(); want 4 and the "
                  "same pointer (move must transfer the memory, not copy it)", m.size(), m.data() == p ? "==" : "!=");
    HARNESS_CHECK(a.size() == 0, "Buffer m(std::move(a)): moved-from a.size() = %zu, want 0", a.size());
    Buffer n(1);
    n = std::move(m);
    HARNESS_CHECK(n.data() == p && n.size() == 4 && n[0] == 'x',
                  "Buffer n(1); n = std::move(m) (m has size 4, m[0] = 'x'): n.size() = %zu, n[0] = %d, n.data() %s "
                  "m's old data(); want 4, 'x' (%d) and the same pointer (move assignment must transfer the memory)",
                  n.size(), n[0], n.data() == p ? "==" : "!=", 'x');
    HARNESS_CHECK(m.size() == 0, "n = std::move(m): moved-from m.size() = %zu, want 0", m.size());

    std::vector<Buffer> v;
    for (int i = 0; i < 100; i++) { Buffer t(16); t[0] = char(i); v.push_back(t); v.push_back(std::move(t)); }
    for (int i = 0; i < 100; i++)
        HARNESS_CHECK(v[2 * i][0] == char(i) && v[2 * i + 1][0] == char(i),
                      "std::vector<Buffer> v; for i in 0..99: Buffer t(16); t[0] = i; v.push_back(t); "
                      "v.push_back(std::move(t)): v[%d][0] = %d, v[%d][0] = %d; want %d and %d",
                      2 * i, v[2 * i][0], 2 * i + 1, v[2 * i + 1][0], i, i);
    std::vector<Buffer> w = v;
    HARNESS_CHECK(w.size() == 200 && w[10][0] == char(5),
                  "copy w = v of that vector: w.size() = %zu, w[10][0] = %d; want 200 and 5", w.size(),
                  w.size() > 10 ? w[10][0] : -1);
    std::puts("ok");
}

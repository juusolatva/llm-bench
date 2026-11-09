#include <cstdio>
#include <cstdlib>
#include <string>
#include <utility>
#include <vector>
#include "solution.hpp"

#define HARNESS_CHECK(c, ...) do { if (!(c)) { std::fprintf(stderr, "FAIL: " __VA_ARGS__); std::fputc('\n', stderr); std::exit(1); } } while (0)

// b[i] as an int for failure messages; -1 if i >= b.size() (the solution's size() may be wrong).
static int harness_at(const Buffer& b, std::size_t i) { return i < b.size() ? b[i] : -1; }

// Whether b has exactly the bytes of want: the same size and contents.
static bool harness_holds(const Buffer& b, const std::string& want) {
    if (b.size() != want.size()) return false;
    for (std::size_t i = 0; i < want.size(); i++)
        if (b[i] != want[i]) return false;
    return true;
}

// b's size and (up to 16 of) its bytes for failure messages, e.g. size() = 4, bytes "wx\0\0".
static std::string harness_desc(const Buffer& b) {
    char buf[24];
    std::snprintf(buf, sizeof buf, "%zu", b.size());
    std::string s = std::string("size() = ") + buf + ", bytes \"";
    for (std::size_t i = 0; i < b.size() && i < 16; i++) {
        unsigned char c = static_cast<unsigned char>(b[i]);
        if (c >= 32 && c < 127 && c != '"' && c != '\\') {
            s += static_cast<char>(c);
        } else {
            std::snprintf(buf, sizeof buf, "\\x%02x", c);
            s += buf;
        }
    }
    return s + (b.size() > 16 ? "\"..." : "\"");
}

int main() {
    Buffer a(4);
    HARNESS_CHECK(harness_holds(a, std::string(4, '\0')), "Buffer a(4): %s; want size() 4 and zero-filled",
                  harness_desc(a).c_str());
    for (int i = 0; i < 4; i++) a[i] = "wxyz"[i];
    {
        Buffer b = a;
        HARNESS_CHECK(harness_holds(b, "wxyz"), "Buffer b = a (a has the 4 bytes \"wxyz\"): b has %s; want \"wxyz\"",
                      harness_desc(b).c_str());
        b[0] = 'y';
        HARNESS_CHECK(harness_holds(a, "wxyz"),
                      "Buffer b = a; b[0] = 'y' (a had \"wxyz\"): a has %s, want \"wxyz\"; copies must be independent",
                      harness_desc(a).c_str());
        HARNESS_CHECK(b.data() != a.data(), "Buffer b = a: b.data() == a.data(); a copy must have its own memory");
    }
    HARNESS_CHECK(harness_holds(a, "wxyz"), "after a copy of a (\"wxyz\") was destroyed: a has %s, want \"wxyz\"",
                  harness_desc(a).c_str());
    {
        Buffer c(2);
        c = a;
        HARNESS_CHECK(harness_holds(c, "wxyz"), "Buffer c(2); c = a (a has the 4 bytes \"wxyz\"): c has %s; want \"wxyz\"",
                      harness_desc(c).c_str());
        c[1] = '!';
        HARNESS_CHECK(harness_holds(a, "wxyz"),
                      "c = a; c[1] = '!' (a had \"wxyz\"): a has %s, want \"wxyz\"; copy assignment must make an "
                      "independent copy", harness_desc(a).c_str());
    }
    Buffer& ref = a;
    a = ref;
    HARNESS_CHECK(harness_holds(a, "wxyz"), "self-assignment a = a (a has \"wxyz\"): a has %s; want \"wxyz\"",
                  harness_desc(a).c_str());

    char* p = a.data();
    Buffer m(std::move(a));
    HARNESS_CHECK(m.data() == p && m.size() == 4,
                  "Buffer m(std::move(a)) (a has size 4): m.size() = %zu, m.data() %s a's old data(); want 4 and the "
                  "same pointer (move must transfer the memory, not copy it)", m.size(), m.data() == p ? "==" : "!=");
    HARNESS_CHECK(a.size() == 0, "Buffer m(std::move(a)): moved-from a.size() = %zu, want 0", a.size());
    Buffer n(1);
    n = std::move(m);
    HARNESS_CHECK(n.data() == p && harness_holds(n, "wxyz"),
                  "Buffer n(1); n = std::move(m) (m has \"wxyz\"): n has %s, n.data() %s m's old data(); want \"wxyz\" "
                  "and the same pointer (move assignment must transfer the memory)",
                  harness_desc(n).c_str(), n.data() == p ? "==" : "!=");
    HARNESS_CHECK(m.size() == 0, "n = std::move(m): moved-from m.size() = %zu, want 0", m.size());

    // Buffers of 16 bytes with distinct first and last bytes, so a copy of only part of the bytes is caught.
    std::vector<Buffer> v;
    for (int i = 0; i < 100; i++) {
        Buffer t(16);
        t[0] = char(i);
        t[15] = char(i + 1);
        v.push_back(t);
        v.push_back(std::move(t));
    }
    for (int i = 0; i < 100; i++)
        HARNESS_CHECK(harness_at(v[2 * i], 0) == i && harness_at(v[2 * i], 15) == i + 1 &&
                      harness_at(v[2 * i + 1], 0) == i && harness_at(v[2 * i + 1], 15) == i + 1,
                      "std::vector<Buffer> v; for i in 0..99: Buffer t(16); t[0] = i; t[15] = i + 1; v.push_back(t); "
                      "v.push_back(std::move(t)): v[%d][0] = %d, v[%d][15] = %d, v[%d][0] = %d, v[%d][15] = %d; want "
                      "%d, %d, %d and %d", 2 * i, harness_at(v[2 * i], 0), 2 * i, harness_at(v[2 * i], 15), 2 * i + 1,
                      harness_at(v[2 * i + 1], 0), 2 * i + 1, harness_at(v[2 * i + 1], 15), i, i + 1, i, i + 1);
    std::vector<Buffer> w = v;
    HARNESS_CHECK(w.size() == 200 && harness_at(w[10], 0) == 5 && harness_at(w[10], 15) == 6,
                  "copy w = v of that vector: w.size() = %zu, w[10][0] = %d, w[10][15] = %d; want 200, 5 and 6",
                  w.size(), w.size() > 10 ? harness_at(w[10], 0) : -1, w.size() > 10 ? harness_at(w[10], 15) : -1);
    std::puts("harness: all checks passed");
}

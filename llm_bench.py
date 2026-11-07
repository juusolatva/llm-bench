#!/usr/bin/env python3
"""Benchmark LLMs served over an OpenAI-compatible API on Python, C, C++, Rust, Go and Bash tasks.

Works with any server exposing /v1/models and /v1/chat/completions (Ollama, LM Studio,
llama.cpp server, vLLM, ...). Generated code is built and run against a hidden test harness per task.
Output: results_<endpoint>.csv (one row per model x task) and runs/<endpoint>/<model>/<task>/
attempt_<n>/ (response.md = raw model reply, log.txt = build/test output).
Requires Linux, bubblewrap, a user systemd manager with cgroup v2 limits, and
toolchains on PATH: python3, gcc, g++, rustc, go, bash (+ coreutils/findutils).
Run with --help for usage.
"""
import argparse
import csv
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from fnmatch import fnmatchcase
from pathlib import Path

# --- CONFIGURATION ---
# Defaults for the command-line options (see --help).
DEFAULT_TIMEOUT_S = 1800       # per request: ~max tokens / slowest model's tok/s (at long context) + load time
DEFAULT_MAX_TOKENS = 16384     # worst-case prompt (~9k tokens) + max tokens must fit in the context window
DEFAULT_ATTEMPTS = 3           # 1 = no feedback; N = initial attempt + N-1 attempts with build/test feedback
MAX_CONSECUTIVE_FAILURES = 3   # stop an endpoint after this many connection failures in a row
FEEDBACK_CHARS = 6000          # max characters of failing build/test output sent back to the model
FEEDBACK = (
    "Your solution failed. Output of `{cmd}`:\n```\n{out}\n```\n"
    "Fix the problem. Reply with exactly one fenced code block containing the complete corrected file."
)
CMD_TIMEOUT_S = 60
SANDBOX_MEMORY_BYTES = 2 * 1024**3
SANDBOX_TASKS = 128
SANDBOX_TMP_BYTES = 512 * 1024**2
SANDBOX_FILE_BYTES = 64 * 1024**2
MAX_OUTPUT_BYTES = 1024**2
MAX_RESPONSE_BYTES = 8 * 1024**2  # API reply body cap, enforced before JSON parsing
MAX_CONTENT_CHARS = 1024**2        # completion text cap, enforced before anything is written under runs/
# Only the resolved Rust toolchain is exposed, never ~/.cargo or all of ~/.rustup.
RUST_SYSROOT = None

SYSTEM = (
    "You are an expert programmer. Reply with exactly one fenced code block containing the complete "
    "contents of the requested file. Do not include tests, example usage, or a main function."
)

SAN = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
LANGS = {
    "python": {"sol": "solution.py", "test": "test_solution.py",
               "cmds": [["python3", "test_solution.py"]]},
    "c": {"sol": "solution.c", "test": "test.c",
          "cmds": [["gcc", "-std=gnu17", "-O1", "-g", "-Wall", *SAN, "solution.c", "test.c", "-o", "t", "-lm"],
                   ["./t"]]},
    "cpp": {"sol": "solution.hpp", "test": "test.cpp",
            "cmds": [["g++", "-std=c++20", "-O1", "-g", "-Wall", *SAN, "-pthread", "test.cpp", "-o", "t"],
                     ["./t"]]},
    # Rust: the test module is appended to the solution file.
    "rust": {"sol": "lib.rs", "test": None,
             "cmds": [["rustc", "--edition", "2021", "--test", "-O", "-o", "t", "lib.rs"], ["./t"]]},
    "go": {"sol": "solution.go", "test": "solution_test.go",
           "extra": {"go.mod": "module solution\n\ngo 1.22\n"},
           "cmds": [["go", "test", "-race", "-count=1", "."]]},
    "bash": {"sol": "solution.sh", "test": "test.sh",
             "cmds": [["bash", "test.sh"]]},
}

# --------------------------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------------------------
# 4 tasks per language: 3 "write this" tasks of increasing difficulty and 1 "fix this code" task.
# Tests check only what the prompt states.

# ---------------------------------- Python ----------------------------------

PY_DURATION_PROMPT = """Write a Python function `parse_duration(s: str) -> int` in solution.py that converts a duration string such as "1h30m", "45s" or "2h5m10s" to a number of seconds.

- The units are h, m and s, each preceded by a non-negative integer.
- Each unit appears at most once and in the order h, m, s. Any unit may be omitted, but at least one must be present.
- No spaces or other characters are allowed.
- Raise ValueError for invalid input."""

PY_DURATION_TEST = r"""
from solution import parse_duration

ok = {"1h30m": 5400, "45s": 45, "2h": 7200, "2h5m10s": 7510, "0s": 0, "90m": 5400,
      "1h0m5s": 3605, "100s": 100, "1h1s": 3601}
for s, want in ok.items():
    got = parse_duration(s)
    assert got == want, f"{s!r}: got {got!r}, want {want}"
for s in ["", "h", "10", "1x", "1m1h", "1h1h", "1h 30m", "-5s", "1.5h", "1hm", "s5"]:
    try:
        parse_duration(s)
    except ValueError:
        continue
    raise AssertionError(f"{s!r}: expected ValueError")
print("ok")
"""

PY_TOPCUST_PROMPT = """This function in solution.py returns wrong results: the order is wrong, ties are not ordered as the docstring says, and calling it twice with the same input gives different results. Fix it and reply with the complete fixed solution.py.

```python
def top_customers(rows, n=3, totals={}):
    \"\"\"rows: iterable of (customer, amount) tuples.
    Return the n customers with the highest total amount as a list of (customer, total) tuples,
    highest total first; customers with equal totals are ordered by name ascending.\"\"\"
    for customer, amount in rows:
        totals[customer] = totals.get(customer, 0) + amount
    ranked = sorted(totals.items(), key=lambda kv: kv[1])
    return ranked[:n]
```"""

PY_TOPCUST_TEST = r"""
from solution import top_customers

rows = [("bob", 5), ("alice", 10), ("carol", 5), ("dave", 1)]
want = [("alice", 10), ("bob", 5), ("carol", 5)]
assert top_customers(rows) == want, top_customers(rows)
assert top_customers(rows) == want, "second call differs (state kept between calls)"
assert top_customers(rows, n=10) == [("alice", 10), ("bob", 5), ("carol", 5), ("dave", 1)]
assert top_customers([("a", 1), ("b", 2), ("a", 2)], n=2) == [("a", 3), ("b", 2)]
assert top_customers([]) == []
assert top_customers((r for r in [("x", 1), ("y", 1)]), n=1) == [("x", 1)]
print("ok")
"""

PY_MERGE_PROMPT = """Write a Python function `deep_merge(a: dict, b: dict) -> dict` in solution.py.

- Return a new dict containing the keys of both a and b.
- When a key exists in both and both values are dicts, merge them recursively. Otherwise the value from b wins (lists and other values are not merged).
- a and b must not be modified, and modifying the result (including nested dicts and lists) must never affect a or b."""

PY_MERGE_TEST = r"""
import copy
from solution import deep_merge

a = {"x": 1, "n": {"p": 1, "q": {"r": 1}}, "l": [1], "only_a": {"k": [1, 2]}}
b = {"y": 2, "n": {"q": {"s": 2}, "t": 3}, "l": [2], "only_b": {"k": [3]}}
a0, b0 = copy.deepcopy(a), copy.deepcopy(b)
r = deep_merge(a, b)
assert r == {"x": 1, "y": 2, "n": {"p": 1, "q": {"r": 1, "s": 2}, "t": 3}, "l": [2],
             "only_a": {"k": [1, 2]}, "only_b": {"k": [3]}}, r
assert a == a0 and b == b0, "inputs modified"
r["n"]["q"]["r"] = 99
r["l"].append(7)
r["only_a"]["k"].append(9)
r["only_b"]["k"].append(9)
r["n"]["new"] = 1
assert a == a0 and b == b0, "result shares objects with inputs"
assert deep_merge({"k": 1}, {"k": {"z": 1}}) == {"k": {"z": 1}}
assert deep_merge({"k": {"z": 1}}, {"k": None}) == {"k": None}
assert deep_merge({}, {}) == {}
print("ok")
"""

PY_RETRY_PROMPT = """Write a decorator factory `retry(times, exceptions=(Exception,), delay=1.0, backoff=2.0)` in solution.py.

- The decorated function is called at most `times` times in total.
- If a call raises an exception that is an instance of one of `exceptions`, wait and call it again: wait `delay` seconds before the 2nd call, `delay * backoff` before the 3rd, `delay * backoff**2` before the 4th, and so on. Use `time.sleep` to wait. Do not wait after the last call.
- If every call fails, re-raise the exception from the last call. Exceptions not listed in `exceptions` propagate immediately without retrying.
- Return the result as soon as a call succeeds. Positional and keyword arguments are passed through, and the decorated function keeps its `__name__` and `__doc__`.
- `retry(...)` raises ValueError if `times < 1`."""

PY_RETRY_TEST = r"""
import math, time
sleeps = []
time.sleep = lambda s: sleeps.append(s)   # patched before import so any import style sees it
from solution import retry

def close(xs, ys):
    return len(xs) == len(ys) and all(math.isclose(x, y) for x, y in zip(xs, ys))

calls = []
@retry(times=4, exceptions=(ValueError,), delay=0.5, backoff=2)
def flaky(x, y=0):
    "doc here"
    calls.append(1)
    if len(calls) < 3:
        raise ValueError("no")
    return x + y
assert flaky(1, y=2) == 3 and len(calls) == 3
assert close(sleeps, [0.5, 1.0]), sleeps
assert flaky.__name__ == "flaky" and flaky.__doc__ == "doc here"

sleeps.clear(); errs = []
@retry(times=3, exceptions=(KeyError, ValueError), delay=1, backoff=3)
def always():
    e = KeyError(len(errs)); errs.append(e); raise e
try:
    always()
except KeyError as e:
    assert e is errs[-1], "must re-raise the last exception"
else:
    raise AssertionError("no exception")
assert len(errs) == 3 and close(sleeps, [1, 3]), (len(errs), sleeps)

sleeps.clear(); n = []
@retry(times=5, exceptions=(ValueError,), delay=1)
def other():
    n.append(1); raise TypeError("x")
try:
    other()
except TypeError:
    pass
else:
    raise AssertionError("no exception")
assert len(n) == 1 and sleeps == [], "unlisted exception must not be retried"

sleeps.clear()
@retry(times=1, delay=1)
def once():
    raise RuntimeError("x")
try:
    once()
except RuntimeError:
    pass
assert sleeps == [], "no sleep after the last call"

for bad in (0, -1):
    try:
        retry(times=bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"times={bad}: expected ValueError")
print("ok")
"""

# ---------------------------------- C ----------------------------------

C_TRIM_PROMPT = """Write C code for solution.c (no main) implementing:

```c
char *trim(char *s);
```

Remove leading and trailing whitespace (as defined by isspace) from the NUL-terminated string s in place: terminate the string after its last non-whitespace character and return a pointer to its first non-whitespace character (a pointer into s). An empty or all-whitespace string becomes an empty string."""

C_TRIM_TEST = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
char *trim(char *s);

static int fails;
static void t(const char *in, const char *want) {
    size_t n = strlen(in) + 1;
    char *s = malloc(n);          /* exact-size heap copy: ASan catches out-of-bounds access */
    memcpy(s, in, n);
    char *r = trim(s);
    if (r < s || r >= s + n || strcmp(r, want) != 0) {
        fprintf(stderr, "trim(\"%s\"): got \"%s\", want \"%s\"\n", in, (r >= s && r < s + n) ? r : "<outside s>", want);
        fails++;
    }
    free(s);
}
int main(void) {
    t("  hello world \t\n", "hello world");
    t("abc", "abc");
    t("", "");
    t("   ", "");
    t("\t\n\r ", "");
    t("\tx", "x");
    t("x  ", "x");
    t(" a b ", "a b");
    if (fails) return 1;
    puts("ok");
    return 0;
}
"""

C_JOIN_PROMPT = """Write C code for solution.c (no main) implementing:

```c
char *join_path(const char *a, const char *b);
```

Return a newly malloc'd string (the caller frees it) that joins two path parts:
- If b starts with '/', it is absolute: return a copy of b.
- If a is empty, return a copy of b. If b is empty, return a copy of a.
- Otherwise remove all trailing '/' characters from a and return a + "/" + b.
- Return NULL if memory allocation fails."""

C_JOIN_TEST = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
char *join_path(const char *a, const char *b);

static int fails;
static char *dup(const char *s) { size_t n = strlen(s) + 1; char *d = malloc(n); memcpy(d, s, n); return d; }
static void t(const char *a, const char *b, const char *want) {
    char *ha = dup(a), *hb = dup(b);  /* exact-size heap copies: ASan catches over-reads */
    char *r = join_path(ha, hb);
    if (!r || strcmp(r, want) != 0) {
        fprintf(stderr, "join_path(\"%s\", \"%s\"): got \"%s\", want \"%s\"\n", a, b, r ? r : "(null)", want);
        fails++;
    }
    free(r); free(ha); free(hb);
}
int main(void) {
    t("usr", "bin", "usr/bin");
    t("usr/", "bin", "usr/bin");
    t("usr///", "bin", "usr/bin");
    t("/", "etc", "/etc");
    t("a", "/etc", "/etc");
    t("", "x", "x");
    t("x", "", "x");
    t("x/", "", "x/");
    t("", "", "");
    t("a/b", "c/d/", "a/b/c/d/");
    if (fails) return 1;
    puts("ok");
    return 0;
}
"""

C_INTVEC_PROMPT = """This dynamic int array in solution.c crashes and corrupts memory. Fix all bugs without changing the struct or the function signatures, and reply with the complete fixed solution.c. iv_remove_at must return -1 when i is out of range.

```c
#include <stdlib.h>
#include <string.h>

typedef struct { int *data; size_t len, cap; } intvec;

void iv_init(intvec *v) { v->data = NULL; v->len = 0; v->cap = 0; }

int iv_push(intvec *v, int x) {
    if (v->len == v->cap) {
        v->cap *= 2;
        v->data = realloc(v->data, v->cap);
        if (!v->data) return -1;
    }
    v->data[v->len++] = x;
    return 0;
}

/* Remove element i, shifting the following elements left. Returns 0, or -1 if i is out of range. */
int iv_remove_at(intvec *v, size_t i) {
    if (i > v->len) return -1;
    memmove(&v->data[i], &v->data[i + 1], v->len - i);
    v->len--;
    return 0;
}

void iv_free(intvec *v) { free(v->data); }
```"""

C_INTVEC_TEST = r"""
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct { int *data; size_t len, cap; } intvec;
void iv_init(intvec *v);
int iv_push(intvec *v, int x);
int iv_remove_at(intvec *v, size_t i);
void iv_free(intvec *v);

#define CHECK(c, msg) do { if (!(c)) { fprintf(stderr, "FAIL: %s\n", msg); exit(1); } } while (0)

int main(void) {
    intvec e; iv_init(&e);
    CHECK(iv_remove_at(&e, 0) == -1, "remove_at on empty vector must return -1");
    iv_free(&e);

    intvec v; iv_init(&v);
    int ref[1000]; size_t n = 0;
    for (int i = 0; i < 1000; i++) { CHECK(iv_push(&v, i) == 0, "push failed"); ref[n++] = i; }
    CHECK(v.len == 1000, "len after pushes");
    size_t idx[] = {0, 998, 500, 1, 250};
    for (size_t k = 0; k < sizeof idx / sizeof idx[0]; k++) {
        size_t i = idx[k] < n ? idx[k] : n - 1;
        CHECK(iv_remove_at(&v, i) == 0, "remove_at failed");
        for (size_t j = i; j + 1 < n; j++) ref[j] = ref[j + 1];
        n--;
    }
    CHECK(iv_remove_at(&v, v.len) == -1, "remove_at(len) must return -1");
    CHECK(iv_remove_at(&v, v.len + 5) == -1, "remove_at(len+5) must return -1");
    CHECK(v.len == n, "len after removes");
    for (size_t j = 0; j < n; j++) CHECK(v.data[j] == ref[j], "contents wrong after removes");
    CHECK(iv_remove_at(&v, v.len - 1) == 0 && v.len == n - 1, "remove last element");
    iv_free(&v);
    puts("ok");
    return 0;
}
"""

C_KV_PROMPT = """Write C code for solution.c (no main) implementing:

```c
#include <stddef.h>
int parse_kv(const char *line, char *key, size_t keysz, char *val, size_t valsz);
```

It parses one line of a config file of the form `key = value`:
- Lines that are empty, contain only whitespace, or whose first non-whitespace character is '#' are skipped: return 0.
- The key is the text before the first '=', the value is everything after it. Whitespace (isspace, including a trailing "\\n" or "\\r\\n") at the start and end of both is removed; whitespace inside them is kept. The value may be empty.
- On success, copy key and value as NUL-terminated strings into key and val and return 1.
- Return -1 if there is no '=', the key is empty, or the key or the value (including its NUL) does not fit into keysz or valsz bytes.
- Never write more than keysz bytes to key or valsz bytes to val."""

C_KV_TEST = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int parse_kv(const char *line, char *key, size_t keysz, char *val, size_t valsz);

static int fails;
static void t(const char *line, size_t ks, size_t vs, int want, const char *wk, const char *wv) {
    size_t n = strlen(line) + 1;
    char *l = malloc(n); memcpy(l, line, n);
    char *k = malloc(ks), *v = malloc(vs);   /* exact sizes: ASan catches overflows */
    int r = parse_kv(l, k, ks, v, vs);
    if (r != want || (want == 1 && (strcmp(k, wk) != 0 || strcmp(v, wv) != 0))) {
        fprintf(stderr, "parse_kv(\"%s\", %zu, %zu): got %d", line, ks, vs, r);
        if (r == 1) fprintf(stderr, " key=\"%s\" val=\"%s\"", k, v);
        fprintf(stderr, ", want %d", want);
        if (want == 1) fprintf(stderr, " key=\"%s\" val=\"%s\"", wk, wv);
        fprintf(stderr, "\n");
        fails++;
    }
    free(l); free(k); free(v);
}
int main(void) {
    t("name = Bob\n", 32, 32, 1, "name", "Bob");
    t("  path=/usr/local/bin  ", 32, 32, 1, "path", "/usr/local/bin");
    t("greeting = hello world \r\n", 32, 32, 1, "greeting", "hello world");
    t("my key = v", 32, 32, 1, "my key", "v");
    t("empty =", 32, 32, 1, "empty", "");
    t("a=b=c", 32, 32, 1, "a", "b=c");
    t("# comment", 32, 32, 0, 0, 0);
    t("   # indented = comment", 32, 32, 0, 0, 0);
    t("", 32, 32, 0, 0, 0);
    t("   \n", 32, 32, 0, 0, 0);
    t("novalue", 32, 32, -1, 0, 0);
    t("= x", 32, 32, -1, 0, 0);
    t("   =x", 32, 32, -1, 0, 0);
    t("abc=1", 4, 32, 1, "abc", "1");
    t("abcd=1", 4, 32, -1, 0, 0);
    t("k=abc", 4, 4, 1, "k", "abc");
    t("k=abcd", 4, 4, -1, 0, 0);
    if (fails) return 1;
    puts("ok");
    return 0;
}
"""

# ---------------------------------- C++ ----------------------------------

CPP_SPLIT_PROMPT = """Write a C++17 header solution.hpp (no main) with:

```cpp
std::vector<std::string> split(const std::string& s, char delim);
```

It splits s at every occurrence of delim. Empty fields are kept: split("a,,b", ',') is {"a", "", "b"}, split("", ',') is {""} and split(",", ',') is {"", ""}."""

CPP_SPLIT_TEST = r"""
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
"""

CPP_WORDS_PROMPT = """Write a C++17 header solution.hpp (no main) with:

```cpp
std::vector<std::pair<std::string, int>> top_words(const std::string& text, std::size_t n);
```

Words are maximal runs of ASCII letters (A-Z, a-z). Count them case-insensitively and return them in lowercase. Return the n most frequent words with their counts, most frequent first; words with equal counts are ordered alphabetically. If there are fewer than n distinct words, return all of them."""

CPP_WORDS_TEST = r"""
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
    std::puts("ok");
}
"""

CPP_BUFFER_PROMPT = """Copying or assigning a Buffer from this solution.hpp crashes the program. Fix the class so that copies are independent deep copies, copy assignment works (including self-assignment), and moving a Buffer transfers ownership of its memory without copying the data (a moved-from Buffer has size() 0). Keep the existing public interface. Reply with the complete fixed solution.hpp.

```cpp
#pragma once
#include <cstddef>
#include <cstring>

class Buffer {
public:
    explicit Buffer(std::size_t size) : size_(size), data_(new char[size]) {
        std::memset(data_, 0, size_);
    }
    ~Buffer() { delete data_; }
    std::size_t size() const { return size_; }
    char& operator[](std::size_t i) { return data_[i]; }
    const char& operator[](std::size_t i) const { return data_[i]; }
    char* data() { return data_; }
private:
    std::size_t size_;
    char* data_;
};
```"""

CPP_BUFFER_TEST = r"""
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
"""

CPP_LRU_PROMPT = """Write a C++17 header solution.hpp (no main) with this class template:

```cpp
template <typename K, typename V>
class LruCache {
public:
    explicit LruCache(std::size_t capacity);  // capacity >= 1
    std::optional<V> get(const K& key);       // the value, and key becomes the most recently used; std::nullopt if absent
    void put(const K& key, const V& value);   // insert or update; key becomes the most recently used;
                                              // if size() would exceed capacity, evict the least recently used key
    std::size_t size() const;
};
```

get and put must run in O(1) on average. K works with std::hash and ==."""

CPP_LRU_TEST = r"""
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
"""

# ---------------------------------- Rust ----------------------------------

RUST_WC_PROMPT = """Write Rust code for a library file (no main, no tests) with:

```rust
pub fn word_count(text: &str) -> std::collections::HashMap<String, usize>
```

Words are maximal runs of alphanumeric characters (char::is_alphanumeric). Count them case-insensitively; the map keys are the lowercase words."""

RUST_WC_TEST = r"""
#[cfg(test)]
mod harness_tests {
    use super::*;
    use std::collections::HashMap;
    fn m(v: &[(&str, usize)]) -> HashMap<String, usize> { v.iter().map(|(k, n)| (k.to_string(), *n)).collect() }

    #[test] fn basic() {
        assert_eq!(word_count("Hello, hello WORLD! world? 42 42 x"), m(&[("hello", 2), ("world", 2), ("42", 2), ("x", 1)]));
    }
    #[test] fn empty() {
        assert_eq!(word_count(""), m(&[]));
        assert_eq!(word_count(" ,.! "), m(&[]));
    }
    #[test] fn split_on_punctuation() {
        assert_eq!(word_count("don't stop-now"), m(&[("don", 1), ("t", 1), ("stop", 1), ("now", 1)]));
    }
    #[test] fn unicode() {
        assert_eq!(word_count("Straße STRASSE straße Ünïcode"), m(&[("straße", 2), ("strasse", 1), ("ünïcode", 1)]));
    }
}
"""

RUST_VERSION_PROMPT = """Write Rust code for a library file (no main, no tests) defining a semantic version type:

- `pub struct Version { pub major: u64, pub minor: u64, pub patch: u64 }` deriving Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord and Hash (versions compare by major, then minor, then patch).
- Implement `std::str::FromStr` with `type Err = String`. Accept exactly three dot-separated non-negative integers, optionally prefixed by a single 'v' (for example "1.2.3" or "v10.0.1"). Anything else is an error.
- Implement `std::fmt::Display`, printing "MAJOR.MINOR.PATCH" without a 'v'."""

RUST_VERSION_TEST = r"""
#[cfg(test)]
mod harness_tests {
    use super::*;
    fn v(a: u64, b: u64, c: u64) -> Version { Version { major: a, minor: b, patch: c } }

    #[test] fn parse_ok() {
        assert_eq!("1.2.3".parse::<Version>(), Ok(v(1, 2, 3)));
        assert_eq!("v10.0.1".parse::<Version>(), Ok(v(10, 0, 1)));
        assert_eq!("0.0.0".parse::<Version>(), Ok(v(0, 0, 0)));
    }
    #[test] fn parse_err() {
        for s in ["", "1.2", "1.2.3.4", "1..3", "a.b.c", "v", "vv1.2.3", "1.2.-3", " 1.2.3", "1.2.3 ", "1.2.x", "V1.2.3"] {
            assert!(s.parse::<Version>().is_err(), "{:?} should be an error", s);
        }
    }
    #[test] fn display_and_order() {
        assert_eq!(v(1, 2, 3).to_string(), "1.2.3");
        assert_eq!("v4.5.6".parse::<Version>().unwrap().to_string(), "4.5.6");
        let mut list: Vec<Version> = ["1.10.0", "1.2.0", "0.9.9", "1.2.10", "1.2.9"].iter().map(|s| s.parse().unwrap()).collect();
        list.sort();
        let out: Vec<String> = list.iter().map(|x| x.to_string()).collect();
        assert_eq!(out, ["0.9.9", "1.2.0", "1.2.9", "1.2.10", "1.10.0"]);
    }
}
"""

RUST_INV_PROMPT = """This Rust library code doesn't compile, and `get()` panics for unknown items instead of returning 0. Fix it without changing the public API and reply with the complete fixed file.

```rust
pub struct Inventory {
    items: Vec<(String, u32)>,
}

impl Inventory {
    pub fn new() -> Self {
        Inventory { items: Vec::new() }
    }

    /// Adds qty units of name.
    pub fn add(&mut self, name: &str, qty: u32) {
        for item in self.items.iter() {
            if item.0 == name {
                item.1 += qty;
                return;
            }
        }
        self.items.push((name.to_string(), qty));
    }

    /// Removes qty units of name. Errors if the item is unknown or there are not enough units
    /// (the inventory is then unchanged). Items whose quantity drops to 0 are removed.
    pub fn remove(&mut self, name: &str, qty: u32) -> Result<(), String> {
        let item = self.items.iter_mut().find(|i| i.0 == name).ok_or("unknown item")?;
        if item.1 < qty {
            return Err(format!("only {} left", item.1));
        }
        item.1 -= qty;
        if item.1 == 0 {
            self.items.retain(|i| i.0 != name);
        }
        Ok(())
    }

    /// Quantity of name (0 if unknown).
    pub fn get(&self, name: &str) -> u32 {
        self.items.iter().find(|i| i.0 == name).unwrap().1
    }

    /// Number of distinct items.
    pub fn len(&self) -> usize {
        self.items.len()
    }
}
```"""

RUST_INV_TEST = r"""
#[cfg(test)]
mod harness_tests {
    use super::*;
    #[test] fn add_and_get() {
        let mut inv = Inventory::new();
        assert_eq!(inv.get("apple"), 0);
        inv.add("apple", 3);
        inv.add("pear", 1);
        inv.add("apple", 2);
        assert_eq!(inv.get("apple"), 5);
        assert_eq!(inv.get("pear"), 1);
        assert_eq!(inv.len(), 2);
    }
    #[test] fn remove() {
        let mut inv = Inventory::new();
        inv.add("apple", 5);
        assert!(inv.remove("apple", 2).is_ok());
        assert_eq!(inv.get("apple"), 3);
        assert!(inv.remove("apple", 4).is_err());
        assert_eq!(inv.get("apple"), 3);
        assert!(inv.remove("kiwi", 1).is_err());
        assert!(inv.remove("apple", 3).is_ok());
        assert_eq!(inv.get("apple"), 0);
        assert_eq!(inv.len(), 0);
    }
}
"""

RUST_CSV_PROMPT = """Write Rust code for a library file (no main, no tests) with:

```rust
pub fn parse_csv_line(line: &str) -> Result<Vec<String>, String>
```

It splits one CSV line into fields:
- Fields are separated by commas. An empty line is a single empty field.
- A field that starts with a double quote is quoted: commas inside it are literal and `""` inside it stands for one `"`. The quoted field ends at a single `"`, which must be followed by a comma or the end of the line; anything else is an error. A quoted field without a closing quote is an error.
- Unquoted fields are taken literally (no trimming) and must not contain a double quote (error)."""

RUST_CSV_TEST = r"""
#[cfg(test)]
mod harness_tests {
    use super::*;
    fn ok(v: &[&str]) -> Result<Vec<String>, String> { Ok(v.iter().map(|s| s.to_string()).collect()) }

    #[test] fn plain() {
        assert_eq!(parse_csv_line("a,b,c"), ok(&["a", "b", "c"]));
        assert_eq!(parse_csv_line(""), ok(&[""]));
        assert_eq!(parse_csv_line("a,,c"), ok(&["a", "", "c"]));
        assert_eq!(parse_csv_line(","), ok(&["", ""]));
        assert_eq!(parse_csv_line(" a , b "), ok(&[" a ", " b "]));
    }
    #[test] fn quoted() {
        assert_eq!(parse_csv_line("\"x,y\",z"), ok(&["x,y", "z"]));
        assert_eq!(parse_csv_line("\"he said \"\"hi\"\"\""), ok(&["he said \"hi\""]));
        assert_eq!(parse_csv_line("\"\""), ok(&[""]));
        assert_eq!(parse_csv_line("a,\"\""), ok(&["a", ""]));
        assert_eq!(parse_csv_line("é,\"ü,ß\""), ok(&["é", "ü,ß"]));
    }
    #[test] fn errors() {
        assert!(parse_csv_line("\"abc").is_err());
        assert!(parse_csv_line("\"a\"b").is_err());
        assert!(parse_csv_line("a\"b").is_err());
        assert!(parse_csv_line("x,\"a\"\"").is_err());
    }
}
"""

# ---------------------------------- Go ----------------------------------

GO_REVERSE_PROMPT = """Write Go code in `package solution` (no main, no tests) with:

```go
func Reverse(s string) string
```

It returns s with its characters (Unicode code points) in reverse order."""

GO_REVERSE_TEST = r"""
package solution

import "testing"

func TestReverse(t *testing.T) {
	cases := map[string]string{"": "", "abc": "cba", "héllo": "olléh", "日本語": "語本日", "a😀b": "b😀a"}
	for in, want := range cases {
		if got := Reverse(in); got != want {
			t.Errorf("Reverse(%q) = %q, want %q", in, got, want)
		}
	}
}
"""

GO_WORDFREQ_PROMPT = """Write Go code in `package solution` (standard library only, no main, no tests) with:

```go
func WordFreq(r io.Reader) (map[string]int, error)
```

It counts the words read from r. Words are maximal runs of letters and digits (unicode.IsLetter or unicode.IsDigit), counted case-insensitively and stored in lowercase. Lines can be longer than 64 KiB. If reading from r fails, return the error."""

GO_WORDFREQ_TEST = r"""
package solution

import (
	"errors"
	"reflect"
	"strings"
	"testing"
	"testing/iotest"
)

func TestBasic(t *testing.T) {
	got, err := WordFreq(strings.NewReader("Hello, hello WORLD!\nworld? 42 42 x\n\ndon't"))
	want := map[string]int{"hello": 2, "world": 2, "42": 2, "x": 1, "don": 1, "t": 1}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, %v; want %v", got, err, want)
	}
}

func TestEmptyAndUnicode(t *testing.T) {
	got, err := WordFreq(strings.NewReader(""))
	if err != nil || len(got) != 0 {
		t.Fatalf("empty input: got %v, %v", got, err)
	}
	got, err = WordFreq(strings.NewReader("Ünïcode ünïcode ÜNÏCODE"))
	if err != nil || got["ünïcode"] != 3 {
		t.Fatalf("unicode: got %v, %v", got, err)
	}
}

func TestLongLine(t *testing.T) {
	line := strings.Repeat("word ", 40000) // 200,000 bytes, no newline
	got, err := WordFreq(strings.NewReader(line))
	if err != nil || got["word"] != 40000 {
		t.Fatalf("long line: got %d, %v", got["word"], err)
	}
}

func TestReadError(t *testing.T) {
	boom := errors.New("boom")
	_, err := WordFreq(iotest.ErrReader(boom))
	if !errors.Is(err, boom) {
		t.Fatalf("got err %v, want boom", err)
	}
}
"""

GO_COUNT_PROMPT = """This Go function sometimes crashes and sometimes returns wrong counts. Fix it (keep it concurrent) and reply with the complete fixed file.

```go
package solution

import "sync"

// CountLengths returns how many strings of each length are in words, computed concurrently.
func CountLengths(words []string) map[int]int {
	counts := map[int]int{}
	var wg sync.WaitGroup
	for _, w := range words {
		go func() {
			wg.Add(1)
			counts[len(w)]++
			wg.Done()
		}()
	}
	wg.Wait()
	return counts
}
```"""

GO_COUNT_TEST = r"""
package solution

import (
	"reflect"
	"strings"
	"testing"
)

func TestCountLengths(t *testing.T) {
	words := make([]string, 5000)
	want := map[int]int{}
	for i := range words {
		words[i] = strings.Repeat("x", i%17)
		want[i%17]++
	}
	for round := 0; round < 20; round++ {
		if got := CountLengths(words); !reflect.DeepEqual(got, want) {
			t.Fatalf("round %d: wrong counts", round)
		}
	}
	if got := CountLengths(nil); len(got) != 0 {
		t.Fatalf("nil input: got %v", got)
	}
}
"""

GO_KV_PROMPT = """Write Go code in `package solution` (standard library only, no main, no tests) with:

```go
func NewHandler() http.Handler
```

It returns an HTTP handler for a small in-memory key-value store:
- `PUT /kv/{key}` stores the request body as the value of key (overwriting any old value) and responds 204 No Content.
- `GET /kv/{key}` responds 200 with the stored value as the body, or 404 if the key does not exist.
- `DELETE /kv/{key}` deletes the key and responds 204, or 404 if the key does not exist.
- Any other method on `/kv/{key}` responds 405 Method Not Allowed.
- key is the non-empty path segment after `/kv/` (no further `/`). Every other path responds 404.
- Every NewHandler() call has its own empty store. The handler is called concurrently from many goroutines."""

GO_KV_TEST = r"""
package solution

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

func harnessDo(h http.Handler, method, path, body string) (int, string) {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec.Code, rec.Body.String()
}

func harnessExpect(t *testing.T, h http.Handler, method, path, body string, code int, want string) {
	t.Helper()
	got, b := harnessDo(h, method, path, body)
	if got != code || (want != "" && b != want) {
		t.Fatalf("%s %s: got %d %q, want %d %q", method, path, got, b, code, want)
	}
}

func TestCRUD(t *testing.T) {
	h := NewHandler()
	harnessExpect(t, h, "GET", "/kv/a", "", 404, "")
	harnessExpect(t, h, "PUT", "/kv/a", "hello", 204, "")
	harnessExpect(t, h, "GET", "/kv/a", "", 200, "hello")
	harnessExpect(t, h, "PUT", "/kv/a", "world", 204, "")
	harnessExpect(t, h, "GET", "/kv/a", "", 200, "world")
	harnessExpect(t, h, "DELETE", "/kv/a", "", 204, "")
	harnessExpect(t, h, "GET", "/kv/a", "", 404, "")
	harnessExpect(t, h, "DELETE", "/kv/a", "", 404, "")
	harnessExpect(t, h, "POST", "/kv/a", "x", 405, "")
	harnessExpect(t, h, "GET", "/kv/", "", 404, "")
	harnessExpect(t, h, "GET", "/other", "", 404, "")
	harnessExpect(t, h, "GET", "/kv/a/b", "", 404, "")
	h2 := NewHandler()
	harnessExpect(t, h, "PUT", "/kv/x", "1", 204, "")
	harnessExpect(t, h2, "GET", "/kv/x", "", 404, "")
}

func TestConcurrent(t *testing.T) {
	h := NewHandler()
	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			key := fmt.Sprintf("/kv/k%d", i)
			for j := 0; j < 20; j++ {
				val := fmt.Sprintf("%d-%d", i, j)
				if c, _ := harnessDo(h, "PUT", key, val); c != 204 {
					t.Errorf("PUT %s: %d", key, c)
					return
				}
				if c, b := harnessDo(h, "GET", key, ""); c != 200 || b != val {
					t.Errorf("GET %s: %d %q, want %q", key, c, b, val)
					return
				}
			}
		}(i)
	}
	wg.Wait()
}
"""

# ---------------------------------- Bash ----------------------------------

BASH_TOPWORDS_PROMPT = """Write a Bash script that takes one argument, FILE, and prints the 3 most frequent words in it, one per line as `COUNT WORD` (single space, no leading spaces), most frequent first. Words with the same count are ordered alphabetically. A word is a maximal run of ASCII letters; words are compared case-insensitively and printed in lowercase. If there are fewer than 3 distinct words, print all of them."""

BASH_TOPWORDS_TEST = r"""
set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT

printf 'The cat and the hat.\nTHE end, cat! Zebra zebra\n' > "$T/in put.txt"
printf '%s\n' '3 the' '2 cat' '2 zebra' > "$T/want"
bash "$SOL" "$T/in put.txt" > "$T/out" 2> "$T/err" < /dev/null || fail "exit status $? ($(cat "$T/err"))"
cmp -s "$T/out" "$T/want" || { diff "$T/want" "$T/out" >&2; fail "case 1 output (want vs got above)"; }

printf 'b a b\n' > "$T/two"
printf '%s\n' '2 b' '1 a' > "$T/want"
bash "$SOL" "$T/two" > "$T/out" 2>/dev/null < /dev/null
cmp -s "$T/out" "$T/want" || { diff "$T/want" "$T/out" >&2; fail "fewer than 3 words (want vs got above)"; }

: > "$T/empty"
bash "$SOL" "$T/empty" > "$T/out" 2>/dev/null < /dev/null
[ ! -s "$T/out" ] || fail "empty file must print nothing"
echo ok
"""

BASH_ROTATE_PROMPT = """Write a Bash script used as `rotate.sh DIR N`. It deletes all but the N most recently modified files whose names end in `.bak` directly inside DIR (not in subdirectories). Other files are never touched. File names may contain spaces.

- Print the path of each deleted file as DIR/NAME (DIR exactly as given) to stdout, one per line, in any order.
- On wrong usage (not exactly 2 arguments, N not a non-negative integer, or DIR not a directory) print an error to stderr and exit 1."""

BASH_ROTATE_TEST = r"""
set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT
cd "$T" || exit 1

setup() {
    rm -rf d; mkdir -p d/sub
    touch -d '2024-01-01' 'd/db 1.bak'
    touch -d '2024-01-02' 'd/db 2.bak'
    touch -d '2024-01-03' 'd/db 3.bak'
    touch -d '2024-01-04' 'd/db 4.bak'
    touch -d '2023-01-01' 'd/notes.txt'
    touch -d '2020-01-01' 'd/sub/old.bak'
}
listing() { (cd d && find . -type f | sort); }

setup
bash "$SOL" d 2 > out 2> err < /dev/null || fail "exit status $? ($(cat err))"
printf '%s\n' './db 3.bak' './db 4.bak' './notes.txt' './sub/old.bak' > want
listing > got
cmp -s got want || { diff want got >&2; fail "N=2: remaining files wrong (want vs got above)"; }
sort out > got
printf '%s\n' 'd/db 1.bak' 'd/db 2.bak' > want
cmp -s got want || { diff want got >&2; fail "N=2: printed paths wrong (want vs got above)"; }

setup
bash "$SOL" d 0 > out 2>/dev/null < /dev/null
printf '%s\n' './notes.txt' './sub/old.bak' > want
listing > got
cmp -s got want || fail "N=0 must delete every .bak in DIR"

setup
bash "$SOL" d 10 > out 2>/dev/null < /dev/null
[ ! -s out ] && [ "$(listing | wc -l)" -eq 6 ] || fail "N larger than the count must delete nothing"

setup
for args in "d" "d 1 x" "d -1" "d abc" "nodir 1"; do
    # shellcheck disable=SC2086
    bash "$SOL" $args > out 2> err < /dev/null
    rc=$?
    [ "$rc" -eq 1 ] || fail "args [$args]: exit $rc, want 1"
    [ -s err ] || fail "args [$args]: no error message"
done
[ "$(listing | wc -l)" -eq 6 ] || fail "usage errors must not delete anything"
echo ok
"""

BASH_RENAME_PROMPT = """This script breaks on file and directory names that contain spaces, and prints an error when no file matches. Fix it: when nothing matches it should do nothing and exit 0; otherwise it should keep working as before. Reply with the complete fixed script.

```bash
#!/bin/bash
# Usage: rename_ext.sh DIR OLD NEW
# Renames every file in DIR whose name ends in .OLD so that it ends in .NEW instead.
dir=$1
for f in $(ls $dir/*.$2); do
    mv $f ${f%.$2}.$3
done
```"""

BASH_RENAME_TEST = r"""
set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT
cd "$T" || exit 1

mkdir 'my dir' empty
touch 'my dir/a file.txt' 'my dir/b.txt' 'my dir/c.md' 'my dir/x.txt.bak'
bash "$SOL" 'my dir' txt log > out 2> err < /dev/null || fail "exit status $? ($(cat err))"
[ ! -s err ] || fail "unexpected stderr: $(cat err)"
(cd 'my dir' && ls -1 | sort) > got
printf '%s\n' 'a file.log' 'b.log' 'c.md' 'x.txt.bak' > want
cmp -s got want || { diff want got >&2; fail "wrong files after rename (want vs got above)"; }

bash "$SOL" empty txt log > out 2> err < /dev/null
rc=$?
[ "$rc" -eq 0 ] || fail "no matches: exit $rc, want 0"
[ ! -s err ] || fail "no matches: stderr not empty: $(cat err)"
echo ok
"""

BASH_ACCESS_PROMPT = """Write a Bash script (awk is fine) that reads the HTTP access log given as its only argument and prints:
- one line `STATUS COUNT` per HTTP status code, sorted by status code ascending,
- then a final line `total_bytes N`, where N is the sum of all response sizes (a size of `-` counts as 0).

Example log line:
`127.0.0.1 - - [10/Oct/2024:13:55:36 +0000] "GET /index.html HTTP/1.1" 200 2326`

On every line the status is the second-to-last field and the size is the last field. Ignore empty lines."""

BASH_ACCESS_TEST = r"""
set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT

cat > "$T/access log" <<'EOF'
127.0.0.1 - - [10/Oct/2024:13:55:36 +0000] "GET /index.html HTTP/1.1" 200 2326
10.0.0.5 - bob [10/Oct/2024:13:55:40 +0000] "GET /missing HTTP/1.1" 404 512

10.0.0.6 - - [10/Oct/2024:13:56:01 +0000] "POST /api/items HTTP/1.1" 500 -
127.0.0.1 - - [10/Oct/2024:13:57:12 +0000] "GET /search?q=a b HTTP/1.1" 200 1000
192.168.1.9 - - [10/Oct/2024:13:58:00 +0000] "GET /img.png HTTP/1.1" 304 -
127.0.0.1 - - [10/Oct/2024:13:59:59 +0000] "GET / HTTP/1.1" 200 74
EOF
printf '%s\n' '200 3' '304 1' '404 1' '500 1' 'total_bytes 3912' > "$T/want"
bash "$SOL" "$T/access log" > "$T/out" 2> "$T/err" < /dev/null || fail "exit status $? ($(cat "$T/err"))"
cmp -s "$T/out" "$T/want" || { diff "$T/want" "$T/out" >&2; fail "output mismatch (want vs got above)"; }
echo ok
"""

TASKS = [
    {"name": "py_parse_duration", "lang": "python", "prompt": PY_DURATION_PROMPT, "test": PY_DURATION_TEST},
    {"name": "py_fix_top_customers", "lang": "python", "prompt": PY_TOPCUST_PROMPT, "test": PY_TOPCUST_TEST},
    {"name": "py_deep_merge", "lang": "python", "prompt": PY_MERGE_PROMPT, "test": PY_MERGE_TEST},
    {"name": "py_retry_decorator", "lang": "python", "prompt": PY_RETRY_PROMPT, "test": PY_RETRY_TEST},
    {"name": "c_trim", "lang": "c", "prompt": C_TRIM_PROMPT, "test": C_TRIM_TEST},
    {"name": "c_join_path", "lang": "c", "prompt": C_JOIN_PROMPT, "test": C_JOIN_TEST},
    {"name": "c_fix_intvec", "lang": "c", "prompt": C_INTVEC_PROMPT, "test": C_INTVEC_TEST},
    {"name": "c_parse_kv", "lang": "c", "prompt": C_KV_PROMPT, "test": C_KV_TEST},
    {"name": "cpp_split", "lang": "cpp", "prompt": CPP_SPLIT_PROMPT, "test": CPP_SPLIT_TEST},
    {"name": "cpp_top_words", "lang": "cpp", "prompt": CPP_WORDS_PROMPT, "test": CPP_WORDS_TEST},
    {"name": "cpp_fix_buffer", "lang": "cpp", "prompt": CPP_BUFFER_PROMPT, "test": CPP_BUFFER_TEST},
    {"name": "cpp_lru_cache", "lang": "cpp", "prompt": CPP_LRU_PROMPT, "test": CPP_LRU_TEST},
    {"name": "rust_word_count", "lang": "rust", "prompt": RUST_WC_PROMPT, "test": RUST_WC_TEST},
    {"name": "rust_version", "lang": "rust", "prompt": RUST_VERSION_PROMPT, "test": RUST_VERSION_TEST},
    {"name": "rust_fix_inventory", "lang": "rust", "prompt": RUST_INV_PROMPT, "test": RUST_INV_TEST},
    {"name": "rust_csv_line", "lang": "rust", "prompt": RUST_CSV_PROMPT, "test": RUST_CSV_TEST},
    {"name": "go_reverse", "lang": "go", "prompt": GO_REVERSE_PROMPT, "test": GO_REVERSE_TEST},
    {"name": "go_word_freq", "lang": "go", "prompt": GO_WORDFREQ_PROMPT, "test": GO_WORDFREQ_TEST},
    {"name": "go_fix_count_lengths", "lang": "go", "prompt": GO_COUNT_PROMPT, "test": GO_COUNT_TEST},
    {"name": "go_kv_http", "lang": "go", "prompt": GO_KV_PROMPT, "test": GO_KV_TEST},
    {"name": "bash_top_words", "lang": "bash", "prompt": BASH_TOPWORDS_PROMPT, "test": BASH_TOPWORDS_TEST},
    {"name": "bash_rotate_backups", "lang": "bash", "prompt": BASH_ROTATE_PROMPT, "test": BASH_ROTATE_TEST},
    {"name": "bash_fix_rename", "lang": "bash", "prompt": BASH_RENAME_PROMPT, "test": BASH_RENAME_TEST},
    {"name": "bash_access_log", "lang": "bash", "prompt": BASH_ACCESS_PROMPT, "test": BASH_ACCESS_TEST},
]

# --------------------------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------------------------

FIELDS = ["endpoint", "model", "task", "lang", "passed", "passed_on", "attempts", "prompt_tokens",
          "completion_tokens", "seconds", "finish_reason"]
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
CODE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
VL_RE = re.compile(r"(?<![a-z0-9])vl(?![a-z0-9])")
UNSAFE_NAME_RE = re.compile(r"[^\w.-]")


PRINT_LOCK = threading.Lock()


def log(msg, err=False):
    """Thread-safe line output (one write per line, so lines from different endpoints never interleave)."""
    with PRINT_LOCK:
        f = sys.stderr if err else sys.stdout
        f.write(msg + "\n")
        f.flush()


def http_json(url, payload=None, timeout=60, api_key=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        # Read one byte past the cap so oversized bodies are caught regardless of Content-Length.
        body = r.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise OSError(f"response from {url} exceeds {MAX_RESPONSE_BYTES} bytes")
    return json.loads(body)


def list_models(name, base, api_key):
    try:
        return [m["id"] for m in http_json(f"{base}/models", timeout=10, api_key=api_key)["data"]]
    except (OSError, KeyError, TypeError, ValueError) as e:
        log(f"{name}: skipping, cannot list models at {base}/models: {e}", err=True)
        return []


def default_model_filter(model_id):
    """Skip embedding models and dedicated vision-language variants ("vl" as a separate name token)."""
    lower = model_id.lower()
    return "embed" not in lower and not VL_RE.search(lower)


def parse_endpoint(spec):
    """'[NAME=]URL' -> (name, base URL). A missing scheme becomes http://, a missing path /v1."""
    name, sep, url = spec.partition("=")
    if not sep or "://" in name:
        name, url = "", spec
    if "://" not in url:
        url = "http://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"invalid endpoint {spec!r}: expected [NAME=]http(s)://HOST[:PORT][/PATH]")
    path = parts.path.rstrip("/") or "/v1"
    base = urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    if not name:
        name = parts.hostname if parts.port is None else f"{parts.hostname}_{parts.port}"
    name = UNSAFE_NAME_RE.sub("_", name)
    return name, base


def extract_code(text):
    text = THINK_RE.sub("", text)
    blocks = CODE_RE.findall(text)
    return blocks[-1] if blocks else text


# This trusted launcher runs before bwrap, outside its hidden /sys. Verify that
# systemd actually applied aggregate limits; unsupported controllers must fail closed.
CGROUP_GUARD = """
import os, sys
from pathlib import Path
relative = next(s.split("::", 1)[1] for s in
                Path("/proc/self/cgroup").read_text().splitlines() if s.startswith("0::"))
group = Path("/sys/fs/cgroup") / relative.lstrip("/")
memory = (group / "memory.max").read_text().strip()
tasks = (group / "pids.max").read_text().strip()
swap = (group / "memory.swap.max").read_text().strip()
quota, period = (group / "cpu.max").read_text().split()
if (memory == "max" or not 0 < int(memory) <= int(sys.argv[1])
        or tasks == "max" or not 0 < int(tasks) <= int(sys.argv[2])
        or swap != "0" or quota == "max" or int(quota) > 2 * int(period)):
    raise SystemExit("sandbox cgroup limits are not enforced")
os.execv(sys.argv[3], sys.argv[3:])
"""


def run_cmd(cmd, cwd):
    """Run only inside a mandatory namespace sandbox and bounded systemd unit."""
    tools = {name: shutil.which(name) for name in ("bwrap", "systemd-run", "systemctl")}
    if not all(tools.values()):
        return -1, "sandbox requires bwrap, systemd-run and systemctl; refusing host execution"
    unit = f"llm-bench-{uuid.uuid4().hex}.service"
    sandbox = [tools["bwrap"], "--unshare-all", "--unshare-user", "--disable-userns", "--die-with-parent",
               "--new-session", "--cap-drop", "ALL", "--clearenv"]
    # Expose runtime/toolchain files, not all of /etc, /home, /run or the host root.
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc/alternatives"):
        if Path(path).exists():
            sandbox += ["--ro-bind", path, path]
    if Path("/etc/ld.so.cache").is_file():
        sandbox += ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"]
    if RUST_SYSROOT is not None:
        sandbox += ["--ro-bind", str(RUST_SYSROOT), "/opt/rust"]
    sandbox += ["--proc", "/proc", "--dev", "/dev",
                "--size", str(SANDBOX_TMP_BYTES), "--tmpfs", "/tmp",
                "--size", str(SANDBOX_TMP_BYTES), "--tmpfs", "/work",
                "--ro-bind", str(Path(cwd).resolve()), "/input", "--chdir", "/work"]
    # Preserve system installations such as /usr/local/go/bin, while excluding
    # home/project/relative PATH entries that are not exposed inside the sandbox.
    system_path = [path for path in os.get_exec_path()
                   if Path(path).is_absolute() and Path(path).resolve().is_relative_to("/usr")]
    sandbox_path = ":".join(["/opt/rust/bin", *system_path, "/usr/bin", "/bin"])
    for key, value in {
        "PATH": sandbox_path, "HOME": "/tmp", "TMPDIR": "/tmp", "LC_ALL": "C",
        "GOCACHE": "/tmp/go-cache", "GOPATH": "/tmp/go", "GOPROXY": "off",
        "GOSUMDB": "off", "GOTOOLCHAIN": "local", "GOMAXPROCS": "2",
    }.items():
        sandbox += ["--setenv", key, value]
    # Copy inputs into private tmpfs. Generated files never reach parent reports,
    # including symlinks named response.md/log.txt or compiler-created artifacts.
    sandbox += ["--", "/bin/bash", "-ec",
                'cp -a /input/. /work/\nexec "$@"', "sandbox", *cmd]
    command = [
        tools["systemd-run"], "--user", "--quiet", "--wait", "--pipe", "--collect",
        f"--unit={unit}", f"--property=MemoryMax={SANDBOX_MEMORY_BYTES}",
        "--property=MemorySwapMax=0", f"--property=TasksMax={SANDBOX_TASKS}",
        "--property=CPUQuota=200%", f"--property=RuntimeMaxSec={CMD_TIMEOUT_S}s",
        "--property=TimeoutStopSec=2s", "--property=KillMode=control-group",
        "--property=OOMPolicy=kill", "--property=NoNewPrivileges=yes",
        "--property=LimitCORE=0", f"--property=LimitFSIZE={SANDBOX_FILE_BYTES}",
        sys.executable, "-c", CGROUP_GUARD, str(SANDBOX_MEMORY_BYTES),
        str(SANDBOX_TASKS), *sandbox,
    ]
    # A regular file plus hard LimitFSIZE bounds output without an unbounded
    # communicate() buffer. Read only a bounded prefix back into the parent.
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT)
            try:
                rc = process.wait(timeout=CMD_TIMEOUT_S + 10)
            finally:
                # Also kill detached descendants after normal completion or interruption.
                try:
                    subprocess.run([tools["systemctl"], "--user", "stop", unit], check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return -1, f"sandbox failed: {exc}"
        output.seek(0)
        data = output.read(MAX_OUTPUT_BYTES + 1)
    text = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if len(data) > MAX_OUTPUT_BYTES:
        return -1, text + "\n[output limit exceeded]"
    return rc, text


def check_sandbox():
    """Fail before contacting endpoints if namespaces or resource limits do not work."""
    with tempfile.TemporaryDirectory(prefix="llm-sandbox-check-") as directory:
        rc, out = run_cmd(["/usr/bin/true"], Path(directory))
    if rc != 0:
        sys.exit(f"sandbox unavailable; refusing to run generated code:\n{out}")


def run_task(task, code, workdir):
    """Write solution + harness into workdir, build and test.
    Returns (passed, log, failing command, failing command output)."""
    lang = LANGS[task["lang"]]
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    if lang["test"] is None:
        (workdir / lang["sol"]).write_text(code + "\n\n" + task["test"])
    else:
        (workdir / lang["sol"]).write_text(code)
        (workdir / lang["test"]).write_text(task["test"])
    for name, content in lang.get("extra", {}).items():
        (workdir / name).write_text(content)
    commands = []
    for cmd in lang["cmds"]:
        rendered = shlex.join(cmd)
        commands += ["printf '%s\\n' " + shlex.quote(f"$ {rendered}"), rendered]
    # Build and execute in one sandbox so private compiler outputs persist only
    # for this attempt. Parent-owned source/transcript files are read-only inputs.
    rc, out = run_cmd(["/bin/bash", "-ec", "\n".join(commands)], workdir)
    run_log = f"{out}\n[exit {rc}]"
    if rc != 0:
        return False, run_log, "build/test", out
    return True, run_log, None, None


def clip(text, limit=FEEDBACK_CHARS):
    """Keep the head (first errors) and tail (summary) of long output."""
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    return text[:head] + "\n[... truncated ...]\n" + text[-(limit - head):]


def check_toolchains(tasks):
    """Verify the toolchains needed by the selected tasks only."""
    global RUST_SYSROOT
    langs = {t["lang"] for t in tasks}
    missing = sorted({cmd[0] for lang in langs for cmd in LANGS[lang]["cmds"]
                      if not cmd[0].startswith("./") and shutil.which(cmd[0]) is None})
    if missing:
        sys.exit(f"missing toolchains on PATH: {', '.join(missing)}\n"
                 f"install them or skip their tasks with --task (e.g. --task 'py_*' --task 'c_*')")
    if "rust" not in langs:
        return
    # rustc may be a rustup proxy under ~/.cargo. Expose the actual compiler
    # installation instead of the proxy, user home or rustup configuration.
    try:
        result = subprocess.run(["rustc", "--print", "sysroot"], check=True,
                                capture_output=True, text=True, timeout=10)
        RUST_SYSROOT = Path(result.stdout.strip()).resolve(strict=True)
        if not (RUST_SYSROOT / "bin/rustc").is_file():
            raise ValueError("Rust sysroot does not contain bin/rustc")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        sys.exit(f"cannot resolve isolated Rust toolchain: {exc}")


def run_endpoint(name, base, models, tasks, opts, out_path, runs_dir):
    """Run the tasks for the given models of one endpoint.
    Appends each row to out_path as it completes; returns the rows."""
    rows = []
    failures = 0          # consecutive connection-level request failures
    # Rows are written as they complete, so an aborted run keeps every finished model x task.
    f = open(out_path, "w", newline="")  # noqa: SIM115 -- closed in the finally below
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    f.flush()
    try:
        for model in models:
            if failures >= MAX_CONSECUTIVE_FAILURES:
                break
            for task in tasks:
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    log(f"{name}: {failures} consecutive request failures, server unreachable; "
                        f"stopping this endpoint", err=True)
                    break
                taskdir = runs_dir / name / UNSAFE_NAME_RE.sub("_", model) / task["name"]
                if taskdir.exists():
                    shutil.rmtree(taskdir)
                messages = [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": task["prompt"]},
                ]
                pt = ct = 0
                secs = 0.0
                passed_on = attempts = 0
                finish = None
                skip = False
                for attempt in range(1, opts.attempts + 1):
                    payload = {
                        "model": model,
                        "max_tokens": opts.max_tokens,
                        "messages": messages,
                    }
                    if opts.temperature is not None:
                        payload["temperature"] = opts.temperature
                    log(f"{name}/{model}/{task['name']}: attempt {attempt}/{opts.attempts}, "
                        f"waiting for response...", err=True)
                    t0 = time.time()
                    try:
                        resp = http_json(f"{base}/chat/completions", payload, timeout=opts.timeout,
                                         api_key=opts.api_key)
                    except OSError as e:
                        secs += time.time() - t0
                        # A bare socket timeout is raised only while waiting for the reply, i.e. the model was
                        # too slow. Connection-level errors (refused, unreachable, connect timeout) arrive wrapped
                        # in URLError: the server is down, which says nothing about the model.
                        if isinstance(e, socket.timeout) and not isinstance(e, urllib.error.URLError):
                            log(f"{name}/{model}/{task['name']}: timed out after {time.time() - t0:.0f}s",
                                err=True)
                            failures = 0  # the server accepted the request, so it is reachable
                            attempts = attempt
                            finish = "timeout"
                        else:
                            log(f"{name}/{model}/{task['name']}: request failed: {e}", err=True)
                            failures += 1
                            skip = True
                        break
                    failures = 0
                    secs += time.time() - t0
                    attempts = attempt
                    choice = resp["choices"][0]
                    text = choice["message"].get("content") or ""
                    finish = choice.get("finish_reason")
                    usage = resp.get("usage") or {}
                    pt += usage.get("prompt_tokens") or 0
                    ct += usage.get("completion_tokens") or 0
                    if len(text) > MAX_CONTENT_CHARS:  # counted as failure, nothing written to disk
                        log(f"{name}/{model}/{task['name']}: response exceeds {MAX_CONTENT_CHARS} chars",
                            err=True)
                        finish = "oversized"
                        break
                    adir = taskdir / f"attempt_{attempt}"
                    passed, run_log, fail_cmd, fail_out = run_task(task, extract_code(text), adir)
                    (adir / "response.md").write_text(text)
                    (adir / "log.txt").write_text(run_log)
                    if passed:
                        passed_on = attempt
                        break
                    if finish == "length":  # hit max tokens: counted as failure, no retry
                        break
                    messages = messages + [
                        {"role": "assistant", "content": THINK_RE.sub("", text).strip()},
                        {"role": "user", "content": FEEDBACK.format(cmd=fail_cmd, out=clip(fail_out))},
                    ]
                if skip:
                    continue
                row = {
                    "endpoint": name,
                    "model": model,
                    "task": task["name"],
                    "lang": task["lang"],
                    "passed": int(passed_on > 0),
                    "passed_on": passed_on,
                    "attempts": attempts,
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "seconds": round(secs, 2),
                    "finish_reason": finish,
                }
                rows.append(row)
                w.writerow(row)
                f.flush()               # keep completed rows on disk if the run is aborted
                log(str(row))
    finally:
        f.close()
    return rows


def print_summary(rows, max_attempts):
    if not rows:
        print("\nno results")
        return
    langs = sorted({r["lang"] for r in rows}, key=list(LANGS).index)
    agg = defaultdict(lambda: {"pass": 0, "p1": 0, "n": 0, "pt": 0, "ct": 0, "s": 0.0,
                               **{lang: [0, 0] for lang in langs}})
    for r in rows:
        a = agg[(r["endpoint"], r["model"])]
        a["pass"] += r["passed"]
        a["p1"] += int(r["passed_on"] == 1)
        a["n"] += 1
        a["pt"] += r["prompt_tokens"]
        a["ct"] += r["completion_tokens"]
        a["s"] += r["seconds"]
        a[r["lang"]][0] += r["passed"]
        a[r["lang"]][1] += 1

    ew = max(8, *(len(e) for e, _ in agg))
    head = (f"\n{'endpoint':{ew}} {'model':40} {'pass@1':>6} {'pass@' + str(max_attempts):>6} "
            + " ".join(f"{lang:>6}" for lang in langs))
    print(head + f" {'prompt_tok':>10} {'compl_tok':>10} {'sec':>8}")
    for (e, m), a in sorted(agg.items(), key=lambda kv: (-kv[1]["pass"], kv[1]["ct"])):
        per = " ".join(f"{a[lang][0]:>4}/{a[lang][1]}" for lang in langs)
        print(f"{e:{ew}} {m[:40]:40} {a['p1']:>3}/{a['n']:<2} {a['pass']:>3}/{a['n']:<2} {per} "
              f"{a['pt']:>10} {a['ct']:>10} {a['s']:>8.1f}")


def positive_int(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


EPILOG = """\
examples:
  %(prog)s http://localhost:11434/v1                       # Ollama
  %(prog)s localhost:1234                                  # LM Studio (/v1 is added)
  %(prog)s box1=gpu-box-1:11434 box2=gpu-box-2:1234        # two servers in parallel
  %(prog)s localhost:8080 -m 'qwen*' --task 'py_*' --task 'rust_*'
  %(prog)s --list-tasks

Endpoints can also be given in the LLM_BENCH_ENDPOINTS environment variable (space-separated).
The API key is read from --api-key, LLM_BENCH_API_KEY or OPENAI_API_KEY, in that order.
"""


def parse_args():
    ap = argparse.ArgumentParser(
        description="Benchmark LLMs served over an OpenAI-compatible API on Python, C, C++, Rust, Go "
                    "and Bash coding tasks. Generated code is built and tested in a sandbox.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("endpoints", nargs="*", metavar="[NAME=]URL",
                    help="OpenAI-compatible base URL(s), e.g. http://localhost:11434/v1. NAME labels the "
                         "endpoint in output (default: HOST_PORT). Multiple endpoints run in parallel")
    ap.add_argument("-m", "--model", action="append", default=[], metavar="PATTERN",
                    help="run only models whose ID matches PATTERN: an exact ID or a shell glob such as "
                         "'google/gemma-4-12b*' (quote it). Repeatable. Default: all models except "
                         "embedding and vision-language (\"vl\") models")
    ap.add_argument("--task", action="append", default=[], metavar="PATTERN",
                    help="run only tasks whose name matches PATTERN (shell glob, e.g. 'py_*'). Repeatable")
    ap.add_argument("--list-tasks", action="store_true", help="list task names and exit")
    ap.add_argument("--api-key", help="bearer token sent to every endpoint")
    ap.add_argument("--timeout", type=positive_int, default=DEFAULT_TIMEOUT_S, metavar="SEC",
                    help="per-request timeout; must cover model load time plus generating max tokens "
                         "on the slowest model (default: %(default)s)")
    ap.add_argument("--max-tokens", type=positive_int, default=DEFAULT_MAX_TOKENS, metavar="N",
                    help="completion token limit per request; prompt (up to ~9k tokens with feedback) + N "
                         "must fit in the model's context window (default: %(default)s)")
    ap.add_argument("--attempts", type=positive_int, default=DEFAULT_ATTEMPTS, metavar="N",
                    help="1 = no feedback; N = first attempt + N-1 retries with build/test output as "
                         "feedback (default: %(default)s)")
    ap.add_argument("--temperature", type=float, metavar="T",
                    help="sampling temperature (default: the server's/model's default)")
    ap.add_argument("-o", "--output-dir", type=Path, default=Path("."), metavar="DIR",
                    help="where results_<endpoint>.csv and runs/ are written (default: current directory)")
    ap.add_argument("-t", "--tag",
                    help="write results_<endpoint>_<TAG>.csv instead of results_<endpoint>.csv")
    args = ap.parse_args()
    if not args.endpoints:
        args.endpoints = os.environ.get("LLM_BENCH_ENDPOINTS", "").split()
    if not args.endpoints and not args.list_tasks:
        ap.error("no endpoint given (e.g. http://localhost:11434/v1 for Ollama, "
                 "http://localhost:1234/v1 for LM Studio)")
    args.api_key = args.api_key or os.environ.get("LLM_BENCH_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if args.tag:
        args.tag = UNSAFE_NAME_RE.sub("_", args.tag)
    return args


def main():
    args = parse_args()
    tasks = [t for t in TASKS if not args.task or any(fnmatchcase(t["name"], p) for p in args.task)]
    if args.list_tasks:
        for t in tasks:
            print(f"{t['name']:24} {t['lang']}")
        return
    for p in args.task:
        if not any(fnmatchcase(t["name"], p) for t in TASKS):
            log(f"warning: task pattern {p!r} matched no task (see --list-tasks)", err=True)
    if not tasks:
        sys.exit("no tasks selected")

    endpoints = {}
    for spec in args.endpoints:
        try:
            name, base = parse_endpoint(spec)
        except ValueError as e:
            sys.exit(str(e))
        if name in endpoints:
            sys.exit(f"duplicate endpoint name {name!r}; label them with NAME=URL")
        endpoints[name] = base

    check_toolchains(tasks)
    check_sandbox()

    plan = {}
    for name, base in endpoints.items():
        ids = list_models(name, base, args.api_key)
        if args.model:
            models = [m for m in ids if any(fnmatchcase(m, p) for p in args.model)]
        else:
            models = [m for m in ids if default_model_filter(m)]
        if models:
            plan[name] = models
            log(f"{name} ({base}): {len(models)} model(s): {', '.join(models)}", err=True)
    for p in args.model:
        if not any(fnmatchcase(m, p) for models in plan.values() for m in models):
            log(f"warning: pattern {p!r} matched no model", err=True)
    if not plan:
        sys.exit("no models selected")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = args.output_dir / "runs"
    suffix = f"_{args.tag}" if args.tag else ""
    with ThreadPoolExecutor(max_workers=len(plan)) as ex:
        futures = [ex.submit(run_endpoint, name, endpoints[name], models, tasks, args,
                             args.output_dir / f"results_{name}{suffix}.csv", runs_dir)
                   for name, models in plan.items()]
        rows = [r for fut in futures for r in fut.result()]
    print_summary(rows, args.attempts)


if __name__ == "__main__":
    main()

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { int *data; size_t len, cap; } intvec;
void iv_init(intvec *v);
int iv_push(intvec *v, int x);
int iv_remove_at(intvec *v, size_t i);
void iv_free(intvec *v);

#define HARNESS_CHECK(c, ...) do { if (!(c)) { fprintf(stderr, "FAIL: " __VA_ARGS__); fputc('\n', stderr); exit(1); } } while (0)

int main(void) {
    intvec e; iv_init(&e);
    int rc = iv_remove_at(&e, 0);
    HARNESS_CHECK(rc == -1, "iv_remove_at(v, 0) on an empty vector: got %d, want -1", rc);
    iv_free(&e);

    intvec v; iv_init(&v);
    int ref[1000]; size_t n = 0;
    for (int i = 0; i < 1000; i++) {
        rc = iv_push(&v, i);
        HARNESS_CHECK(rc == 0, "iv_push(v, %d) (pushing 0, 1, 2, ... in order): got %d, want 0", i, rc);
        ref[n++] = i;
    }
    HARNESS_CHECK(v.len == 1000, "after pushing 0..999: len = %zu, want 1000", v.len);
    for (size_t j = 0; j < n; j++)
        HARNESS_CHECK(v.data[j] == ref[j], "after pushing 0..999: data[%zu] = %d, want %d", j, v.data[j], ref[j]);
    size_t idx[] = {0, 998, 500, 1, 250};
    char done[64] = "";               /* indices removed so far, for messages */
    for (size_t k = 0; k < sizeof idx / sizeof idx[0]; k++) {
        size_t i = idx[k] < n ? idx[k] : n - 1;
        rc = iv_remove_at(&v, i);
        HARNESS_CHECK(rc == 0, "iv_remove_at(v, %zu) with len %zu: got %d, want 0", i, n, rc);
        for (size_t j = i; j + 1 < n; j++) ref[j] = ref[j + 1];
        n--;
        snprintf(done + strlen(done), sizeof done - strlen(done), "%s%zu", k ? ", " : "", i);
        HARNESS_CHECK(v.len == n, "after pushing 0..999 and iv_remove_at at indices %s: len = %zu, want %zu",
                      done, v.len, n);
        for (size_t j = 0; j < n; j++)
            HARNESS_CHECK(v.data[j] == ref[j], "after pushing 0..999 and iv_remove_at at indices %s: "
                          "data[%zu] = %d, want %d", done, j, v.data[j], ref[j]);
    }
    rc = iv_remove_at(&v, v.len);
    HARNESS_CHECK(rc == -1, "iv_remove_at(v, len) with len %zu: got %d, want -1", n, rc);
    rc = iv_remove_at(&v, v.len + 5);
    HARNESS_CHECK(rc == -1, "iv_remove_at(v, len + 5) with len %zu: got %d, want -1", n, rc);
    HARNESS_CHECK(v.len == n, "after out-of-range iv_remove_at calls: len = %zu, want %zu", v.len, n);
    rc = iv_remove_at(&v, v.len - 1);
    HARNESS_CHECK(rc == 0 && v.len == n - 1, "iv_remove_at(v, len - 1) with len %zu: got %d and len %zu, want 0 and len %zu",
                  n, rc, v.len, n - 1);
    iv_free(&v);

    /* The harness shrinks the allocation to exactly len elements (cap = len), so any read or write past len is
       out of bounds and ASan reports it, whatever the growth policy. */
    intvec f; iv_init(&f);
    for (int i = 0; i < 100; i++) {
        rc = iv_push(&f, i);
        HARNESS_CHECK(rc == 0, "iv_push(f, %d) (pushing 0, 1, 2, ... in order): got %d, want 0", i, rc);
    }
    HARNESS_CHECK(f.len == 100, "after pushing 0..99: len = %zu, want 100", f.len);
    for (int round = 0; round < 2; round++) {
        int *shrunk = realloc(f.data, f.len * sizeof *f.data);
        HARNESS_CHECK(shrunk != NULL, "harness: realloc failed");
        f.data = shrunk;
        f.cap = n = f.len;
        size_t i = round == 0 ? 0 : n - 1;
        rc = iv_remove_at(&f, i);
        HARNESS_CHECK(rc == 0 && f.len == n - 1, "iv_remove_at(f, %zu) with len == cap == %zu (allocation shrunk to "
                      "len elements): got %d and len %zu, want 0 and len %zu", i, n, rc, f.len, n - 1);
        for (size_t j = 0; j < f.len; j++)
            HARNESS_CHECK(f.data[j] == (int)j + 1, "after pushing 0..99, iv_remove_at(f, 0)%s: data[%zu] = %d, "
                          "want %d", round ? " and iv_remove_at(f, len - 1)" : "", j, f.data[j], (int)j + 1);
    }
    iv_free(&f);
    puts("harness: all checks passed");
    return 0;
}

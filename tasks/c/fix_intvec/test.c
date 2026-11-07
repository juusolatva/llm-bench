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

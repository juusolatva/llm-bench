#include <stdlib.h>
#include <string.h>

typedef struct { int *data; size_t len, cap; } intvec;

void iv_init(intvec *v) { v->data = NULL; v->len = 0; v->cap = 0; }

int iv_push(intvec *v, int x) {
    if (v->len == v->cap) {
        size_t cap = v->cap ? v->cap * 2 : 8;
        int *data = realloc(v->data, cap * sizeof *data);
        if (!data) return -1;
        v->data = data;
        v->cap = cap;
    }
    v->data[v->len++] = x;
    return 0;
}

/* Remove element i, shifting the following elements left. Returns 0, or -1 if i is out of range. */
int iv_remove_at(intvec *v, size_t i) {
    if (i >= v->len) return -1;
    memmove(&v->data[i], &v->data[i + 1], (v->len - i - 1) * sizeof *v->data);
    v->len--;
    return 0;
}

void iv_free(intvec *v) { free(v->data); v->data = NULL; v->len = 0; v->cap = 0; }

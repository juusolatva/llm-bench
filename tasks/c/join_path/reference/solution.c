#include <stdlib.h>
#include <string.h>

static char *copy_of(const char *s, size_t n) {
    char *r = malloc(n + 1);
    if (!r) return NULL;
    memcpy(r, s, n);
    r[n] = '\0';
    return r;
}

char *join_path(const char *a, const char *b) {
    size_t alen = strlen(a), blen = strlen(b);
    if (b[0] == '/' || alen == 0) return copy_of(b, blen);
    if (blen == 0) return copy_of(a, alen);
    while (alen > 0 && a[alen - 1] == '/') alen--;
    char *r = malloc(alen + 1 + blen + 1);
    if (!r) return NULL;
    memcpy(r, a, alen);
    r[alen] = '/';
    memcpy(r + alen + 1, b, blen + 1);
    return r;
}

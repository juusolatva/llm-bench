#include <stdlib.h>
#include <string.h>

/* A malloc'd NUL-terminated copy of the first n bytes of s, or NULL. */
static char *copy_of(const char *s, size_t n) {
    char *r = malloc(n + 1);
    if (!r) return NULL;
    memcpy(r, s, n);
    r[n] = '\0';
    return r;
}

/* Join two path parts (b wins if absolute; trailing slashes of a are collapsed). Caller frees. */
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

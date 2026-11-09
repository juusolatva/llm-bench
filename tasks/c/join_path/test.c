#include <stdio.h>
#include <stdlib.h>
#include <string.h>
char *join_path(const char *a, const char *b);

static int fails;
/* malloc that exits instead of returning NULL, so a failed allocation isn't blamed on the solution. */
static void *harness_alloc(size_t n) {
    void *p = malloc(n);
    if (!p) { fputs("harness: allocation failed\n", stderr); exit(2); }
    return p;
}
static char *dup(const char *s) { size_t n = strlen(s) + 1; char *d = harness_alloc(n); memcpy(d, s, n); return d; }
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
    puts("harness: all checks passed");
    return 0;
}

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int parse_kv(const char *line, char *key, size_t keysz, char *val, size_t valsz);

static int fails;
/* malloc that exits instead of returning NULL, so a failed allocation isn't blamed on the solution. */
static void *harness_alloc(size_t n) {
    void *p = malloc(n);
    if (!p) { fputs("harness: allocation failed\n", stderr); exit(2); }
    return p;
}
/* Print s in double quotes with control characters escaped (\n, \r, \t, \xNN), so whitespace in inputs is visible. */
static void harness_put_escaped(const char *s) {
    fputc('"', stderr);
    for (; *s; s++) {
        if (*s == '\n') fputs("\\n", stderr);
        else if (*s == '\r') fputs("\\r", stderr);
        else if (*s == '\t') fputs("\\t", stderr);
        else if (*s == '"' || *s == '\\') fprintf(stderr, "\\%c", *s);
        else if ((unsigned char)*s < 0x20 || *s == 0x7f) fprintf(stderr, "\\x%02x", (unsigned char)*s);
        else fputc(*s, stderr);
    }
    fputc('"', stderr);
}
static void t(const char *line, size_t ks, size_t vs, int want, const char *wk, const char *wv) {
    size_t n = strlen(line) + 1;
    char *l = harness_alloc(n); memcpy(l, line, n);
    char *k = harness_alloc(ks), *v = harness_alloc(vs);   /* exact sizes: ASan catches overflows */
    int r = parse_kv(l, k, ks, v, vs);
    if (r == 1 && (!memchr(k, '\0', ks) || !memchr(v, '\0', vs))) {
        fputs("parse_kv(", stderr);
        harness_put_escaped(line);
        fprintf(stderr, ", key, %zu, val, %zu): got 1 with %s not NUL-terminated within its %zu bytes, want %d", ks, vs,
                memchr(k, '\0', ks) ? "val" : "key", memchr(k, '\0', ks) ? vs : ks, want);
        if (want == 1) {
            fputs(" key=", stderr); harness_put_escaped(wk);
            fputs(" val=", stderr); harness_put_escaped(wv);
        }
        fputc('\n', stderr);
        fails++;
    } else if (r != want || (want == 1 && (strcmp(k, wk) != 0 || strcmp(v, wv) != 0))) {
        fputs("parse_kv(", stderr);
        harness_put_escaped(line);
        fprintf(stderr, ", key, %zu, val, %zu): got %d", ks, vs, r);
        if (r == 1) {
            fputs(" key=", stderr); harness_put_escaped(k);
            fputs(" val=", stderr); harness_put_escaped(v);
        }
        fprintf(stderr, ", want %d", want);
        if (want == 1) {
            fputs(" key=", stderr); harness_put_escaped(wk);
            fputs(" val=", stderr); harness_put_escaped(wv);
        }
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
    t("\tkey\t=\t v\tw \t\n", 32, 32, 1, "key", "v\tw");
    t("empty =", 32, 32, 1, "empty", "");
    t("a=b=c", 32, 32, 1, "a", "b=c");
    t("k = a # b", 32, 32, 1, "k", "a # b");
    t("a#b=c", 32, 32, 1, "a#b", "c");
    t("\v\fk\f=\vv\v", 32, 32, 1, "k", "v");
    t("# comment", 32, 32, 0, 0, 0);
    t("   # indented = comment", 32, 32, 0, 0, 0);
    t("", 32, 32, 0, 0, 0);
    t("   \n", 32, 32, 0, 0, 0);
    t(" \t\r\n", 32, 32, 0, 0, 0);
    t("novalue", 32, 32, -1, 0, 0);
    t("= x", 32, 32, -1, 0, 0);
    t("   =x", 32, 32, -1, 0, 0);
    t("abc=1", 4, 32, 1, "abc", "1");
    t("  abc  =  1  ", 4, 2, 1, "abc", "1");
    t("abcd=1", 4, 32, -1, 0, 0);
    t("k=abc", 4, 4, 1, "k", "abc");
    t("k=abcd", 4, 4, -1, 0, 0);
    if (fails) return 1;
    puts("harness: all checks passed");
    return 0;
}

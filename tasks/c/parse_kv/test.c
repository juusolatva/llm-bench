#include <sanitizer/common_interface_defs.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int parse_kv(const char *line, char *key, size_t keysz, char *val, size_t valsz);

static int harness_fails;
/* malloc that exits instead of returning NULL, so a failed allocation isn't blamed on the solution (malloc(0) may
   return NULL; any access through it is an error anyway). */
static void *harness_alloc(size_t n) {
    void *p = malloc(n);
    if (!p && n) { fputs("harness: allocation failed\n", stderr); exit(2); }
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
/* The call in progress, named when a sanitizer stops the program (its report names only lines of the harness). */
static const char *harness_line;
static size_t harness_ks, harness_vs;
static void harness_on_death(void) {
    fputs("the sanitizer stopped the program during parse_kv(", stderr);
    harness_put_escaped(harness_line);
    fprintf(stderr, ", key, %zu, val, %zu), where key has %zu bytes and val has %zu bytes\n", harness_ks, harness_vs,
            harness_ks, harness_vs);
}
/* Whether the n bytes at p contain a NUL (no access when n is 0, where p may be NULL). */
static int harness_has_nul(const char *p, size_t n) { return n > 0 && memchr(p, '\0', n) != NULL; }
static void harness_t(const char *line, size_t ks, size_t vs, int want, const char *wk, const char *wv) {
    harness_line = line, harness_ks = ks, harness_vs = vs;
    size_t n = strlen(line) + 1;
    char *l = harness_alloc(n); memcpy(l, line, n);
    char *k = harness_alloc(ks), *v = harness_alloc(vs);   /* exact sizes: ASan catches overflows */
    if (ks) memset(k, 'X', ks);                             /* malloc(0) may return NULL */
    if (vs) memset(v, 'X', vs);
    int r = parse_kv(l, k, ks, v, vs);
    if (r == 1 && (!harness_has_nul(k, ks) || !harness_has_nul(v, vs))) {
        fputs("parse_kv(", stderr);
        harness_put_escaped(line);
        fprintf(stderr, ", key, %zu, val, %zu): got 1 with %s not NUL-terminated within its %zu bytes, want %d", ks, vs,
                harness_has_nul(k, ks) ? "val" : "key", harness_has_nul(k, ks) ? vs : ks, want);
        if (want == 1) {
            fputs(" key=", stderr); harness_put_escaped(wk);
            fputs(" val=", stderr); harness_put_escaped(wv);
        }
        fputc('\n', stderr);
        harness_fails++;
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
        harness_fails++;
    }
    free(l); free(k); free(v);
}
int main(void) {
    __sanitizer_set_death_callback(harness_on_death);
    harness_t("name = Bob\n", 32, 32, 1, "name", "Bob");
    harness_t("  path=/usr/local/bin  ", 32, 32, 1, "path", "/usr/local/bin");
    harness_t("greeting = hello world \r\n", 32, 32, 1, "greeting", "hello world");
    harness_t("my key = v", 32, 32, 1, "my key", "v");
    harness_t("\tkey\t=\t v\tw \t\n", 32, 32, 1, "key", "v\tw");
    harness_t("empty =", 32, 32, 1, "empty", "");
    harness_t("a=b=c", 32, 32, 1, "a", "b=c");
    harness_t("k = a # b", 32, 32, 1, "k", "a # b");
    harness_t("a#b=c", 32, 32, 1, "a#b", "c");
    harness_t("\v\fk\f=\vv\v", 32, 32, 1, "k", "v");
    harness_t("# comment", 32, 32, 0, 0, 0);
    harness_t("   # indented = comment", 32, 32, 0, 0, 0);
    harness_t("", 32, 32, 0, 0, 0);
    harness_t("   \n", 32, 32, 0, 0, 0);
    harness_t(" \t\r\n", 32, 32, 0, 0, 0);
    harness_t("novalue", 32, 32, -1, 0, 0);
    harness_t("= x", 32, 32, -1, 0, 0);
    harness_t("   =x", 32, 32, -1, 0, 0);
    harness_t("abc=1", 4, 32, 1, "abc", "1");
    harness_t("  abc  =  1  ", 4, 2, 1, "abc", "1");
    harness_t("abcd=1", 4, 32, -1, 0, 0);
    harness_t("k=abc", 4, 4, 1, "k", "abc");
    harness_t("k=abcd", 4, 4, -1, 0, 0);
    harness_t("k=", 32, 1, 1, "k", "");
    harness_t("k=v", 32, 1, -1, 0, 0);
    harness_t("k=", 1, 1, -1, 0, 0);
    harness_t("k=v", 0, 32, -1, 0, 0);
    harness_t("k=v", 32, 0, -1, 0, 0);
    harness_t("# comment", 0, 0, 0, 0, 0);
    if (harness_fails) return 1;
    puts("harness: all checks passed");
    return 0;
}

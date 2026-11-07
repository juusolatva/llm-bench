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

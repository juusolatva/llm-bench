#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int eval_expr(const char *s, long *out);

static int harness_fails;
/* Check eval_expr(expr): want_rc 0 with result want, or -1 with *out left unchanged. */
static void harness_t(const char *expr, int want_rc, long want) {
    size_t n = strlen(expr) + 1;
    char *s = malloc(n);              /* exact-size heap copy: ASan catches over-reads */
    memcpy(s, expr, n);
    long out = 12345;
    int rc = eval_expr(s, &out);
    if (rc != want_rc || (want_rc == 0 && out != want) || (want_rc != 0 && out != 12345)) {
        fprintf(stderr, "eval_expr(\"%s\"): got rc=%d out=%ld, want rc=%d", expr, rc, out, want_rc);
        if (want_rc == 0) fprintf(stderr, " out=%ld\n", want);
        else fprintf(stderr, " and *out unchanged (12345)\n");
        harness_fails++;
    }
    free(s);
}
int main(void) {
    harness_t("1+2*3", 0, 7);
    harness_t("(1+2)*3", 0, 9);
    harness_t(" 10 / 3 ", 0, 3);
    harness_t("-7/2", 0, -3);
    harness_t("7-2-1", 0, 4);
    harness_t("100/10/5", 0, 2);
    harness_t("-(2+3)*2", 0, -10);
    harness_t("2*-3", 0, -6);
    harness_t("-2*3", 0, -6);
    harness_t("--2", 0, 2);
    harness_t("2 - -2", 0, 4);
    harness_t("0", 0, 0);
    harness_t("((42))", 0, 42);
    harness_t("007", 0, 7);
    harness_t("3000000000 * 2", 0, 6000000000L);
    harness_t("1 + 2 * (3 - 4) / 2 - 8", 0, -8);
    harness_t("", -1, 0);
    harness_t("   ", -1, 0);
    harness_t("1+", -1, 0);
    harness_t("*2", -1, 0);
    harness_t("+1", -1, 0);
    harness_t("(1", -1, 0);
    harness_t("1)", -1, 0);
    harness_t("()", -1, 0);
    harness_t("1 2", -1, 0);
    harness_t("2*(3+)", -1, 0);
    harness_t("1/0", -1, 0);
    harness_t("5/(2-2)", -1, 0);
    harness_t("4 % 2", -1, 0);
    harness_t("x", -1, 0);
    if (harness_fails) return 1;
    puts("ok");
    return 0;
}

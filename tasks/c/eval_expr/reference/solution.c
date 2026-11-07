#include <ctype.h>

typedef struct { const char *p; int error; } parser;

static long parse_sum(parser *ps);

static void skip_spaces(parser *ps) {
    while (*ps->p == ' ') ps->p++;
}

static long parse_unary(parser *ps) {
    skip_spaces(ps);
    if (*ps->p == '-') {
        ps->p++;
        return -parse_unary(ps);
    }
    if (*ps->p == '(') {
        ps->p++;
        long v = parse_sum(ps);
        skip_spaces(ps);
        if (*ps->p != ')') { ps->error = 1; return 0; }
        ps->p++;
        return v;
    }
    if (!isdigit((unsigned char)*ps->p)) { ps->error = 1; return 0; }
    long v = 0;
    while (isdigit((unsigned char)*ps->p)) v = v * 10 + (*ps->p++ - '0');
    return v;
}

static long parse_product(parser *ps) {
    long v = parse_unary(ps);
    for (;;) {
        skip_spaces(ps);
        char op = *ps->p;
        if (ps->error || (op != '*' && op != '/')) return v;
        ps->p++;
        long rhs = parse_unary(ps);
        if (ps->error) return 0;
        if (op == '*') {
            v *= rhs;
        } else if (rhs == 0) {
            ps->error = 1;
            return 0;
        } else {
            v /= rhs;
        }
    }
}

static long parse_sum(parser *ps) {
    long v = parse_product(ps);
    for (;;) {
        skip_spaces(ps);
        char op = *ps->p;
        if (ps->error || (op != '+' && op != '-')) return v;
        ps->p++;
        long rhs = parse_product(ps);
        v = op == '+' ? v + rhs : v - rhs;
    }
}

int eval_expr(const char *s, long *out) {
    parser ps = {s, 0};
    long v = parse_sum(&ps);
    skip_spaces(&ps);
    if (ps.error || *ps.p != '\0') return -1;
    *out = v;
    return 0;
}

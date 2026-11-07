Write C code for solution.c (no main) implementing:

```c
int eval_expr(const char *s, long *out);
```

It evaluates the integer arithmetic expression in the NUL-terminated string s:
- Operands are non-negative decimal integers (a run of digits). The operators are binary `+`, `-`, `*`, `/` and unary `-`, and parentheses group subexpressions. There is no unary `+`.
- `*` and `/` bind tighter than `+` and `-`, and binary operators of equal precedence are left-associative. Unary minus binds tighter than any binary operator: `-2*3` is -6, `2*-3` is -6 and `--2` is 2.
- `/` is integer division truncating toward zero, as in C.
- Spaces may appear between tokens, but not inside a number.
- On success, store the result in *out and return 0. Return -1 and leave *out unchanged if the expression is empty or malformed (including any other character) or divides by zero.

All results and intermediate values fit in a long.

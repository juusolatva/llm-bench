Write x86-64 assembly for solution.s (no main) implementing:

```c
#include <stddef.h>
#include <stdint.h>
void stable_sort(uint64_t *a, size_t n, uint64_t *tmp, int (*less)(uint64_t x, uint64_t y));
```

It sorts `a[0..n-1]` in place in the order defined by `less`, so that afterwards `less(a[i + 1], a[i])` is false for every `i`:
- The sort is stable: elements where neither `less(x, y)` nor `less(y, x)` is true keep their original relative order.
- `less` is a strict weak ordering. It returns an `int`: nonzero if `x` must come before `y`, otherwise 0. Only the low 32 bits of `%rax` are defined when it returns.
- `less` follows the System V AMD64 ABI, so it may change every caller-saved register, the flags and the memory below `%rsp`.
- Every call to `less` passes two of the input elements (as values).
- `tmp` points to `n` elements of scratch space; its contents afterwards don't matter.
- It calls `less` at most `n * ceil(log2(n))` times (so not at all for `n` <= 1) and runs in O(n log n) time.
- If `n` is 0, it accesses none of `a`, `tmp` and `less`; `a` and `tmp` may be `NULL`. It writes only `a[0..n-1]` and `tmp[0..n-1]`.

Rules:
- Write GNU assembler (gas) source for x86-64 Linux, in AT&T syntax or with `.intel_syntax noprefix` (not NASM).
- Use only baseline x86-64 instructions (up to SSE2): no SSE3 or later, POPCNT, LZCNT/TZCNT, BMI or AVX, and no `.arch` directive.
- Export only `stable_sort` with `.globl` and keep every other label local. Don't reference any symbol defined outside solution.s (no libc calls).
- Follow the System V AMD64 ABI: preserve `%rbx`, `%rbp`, `%r12`–`%r15` and `%rsp`, keep `%rsp` 16-byte aligned at every `call`, and return with the direction flag clear.

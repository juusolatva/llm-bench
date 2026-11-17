Write x86-64 assembly for solution.s (no main) implementing:

```c
#include <stddef.h>
#include <stdint.h>
uint64_t sum_above(const uint8_t *a, size_t n, uint8_t threshold);
```

It returns the sum of the elements of `a[0..n-1]` (unsigned bytes) that are strictly greater than `threshold`, as a 64-bit total:
- Only the low 8 bits of the register holding `threshold` are defined; its upper bits may hold any value.
- If `n` is 0, it returns 0 without accessing `a`, which may be `NULL`.
- It reads only `a[0..n-1]` and doesn't modify them.

Rules:
- Write GNU assembler (gas) source for x86-64 Linux, in AT&T syntax or with `.intel_syntax noprefix` (not NASM).
- Use only baseline x86-64 instructions (up to SSE2): no SSE3 or later, POPCNT, LZCNT/TZCNT, BMI or AVX, and no `.arch` directive.
- Export only `sum_above` with `.globl` and keep every other label local. Don't reference any symbol defined outside solution.s (no libc calls).
- Follow the System V AMD64 ABI: preserve `%rbx`, `%rbp`, `%r12`–`%r15` and `%rsp`, keep `%rsp` 16-byte aligned at every `call`, and return with the direction flag clear.

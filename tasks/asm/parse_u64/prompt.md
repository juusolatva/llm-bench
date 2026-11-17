Write x86-64 assembly for solution.s (no main) implementing:

```c
#include <stddef.h>
#include <stdint.h>
int parse_u64(const char *s, size_t n, uint64_t *out);
```

It parses `s[0..n-1]` as an unsigned decimal number. `s` is not NUL-terminated: `n` is its length.
- The input must consist only of the decimal digits `0`–`9`; leading zeros are allowed.
- On success, it stores the value in `*out` and returns 0.
- It returns -1 and leaves `*out` unchanged when `n` is 0, when any byte is not a digit (including `'\0'`, spaces, signs and bytes above 127), or when the value exceeds `UINT64_MAX` (18446744073709551615).
- If `n` is 0, it doesn't access `s`, which may be `NULL`. `out` is always valid.
- It reads only `s[0..n-1]`, doesn't modify them, and writes nothing but `*out`.

Rules:
- Write GNU assembler (gas) source for x86-64 Linux, in AT&T syntax or with `.intel_syntax noprefix` (not NASM).
- Use only baseline x86-64 instructions (up to SSE2): no SSE3 or later, POPCNT, LZCNT/TZCNT, BMI or AVX.
- Export only `parse_u64` with `.globl` and keep every other label local. Don't reference any symbol defined outside solution.s (no libc calls).
- Follow the System V AMD64 ABI: preserve `%rbx`, `%rbp`, `%r12`–`%r15` and `%rsp`, keep `%rsp` 16-byte aligned at every `call`, and return with the direction flag clear.

This buf_move in solution.s has bugs. Fix all bugs without changing the function signature, and reply with the complete fixed solution.s.

```c
#include <stddef.h>
void *buf_move(void *dst, const void *src, size_t n);
```

`buf_move` copies `n` bytes from `src` to `dst` as if through a temporary buffer, so the regions may overlap in either direction, and returns `dst`:
- If `n` is 0, it accesses neither pointer; both may be `NULL`.
- It accesses only `src[0..n-1]` and `dst[0..n-1]`, writes only `dst[0..n-1]`, and doesn't modify `src` outside the overlap.

```asm
# void *buf_move(void *dst, const void *src, size_t n)
        .text
        .globl  buf_move
buf_move:
        cmpq    %rsi, %rdi
        ja      .Lbackward
.Lforward:
        movb    (%rsi), %bl
        movb    %bl, (%rdi)
        incq    %rsi
        incq    %rdi
        decq    %rdx
        jnz     .Lforward
        movq    %rdi, %rax
        ret
.Lbackward:
        movq    %rdi, %rax
        leaq    (%rsi,%rdx), %rsi
        leaq    (%rdi,%rdx), %rdi
        movq    %rdx, %rcx
        std
        rep movsb
        ret
```

Rules:
- Write GNU assembler (gas) source for x86-64 Linux, in AT&T syntax or with `.intel_syntax noprefix` (not NASM).
- Use only baseline x86-64 instructions (up to SSE2): no SSE3 or later, POPCNT, LZCNT/TZCNT, BMI or AVX.
- Export only `buf_move` with `.globl` and keep every other label local. Don't reference any symbol defined outside solution.s (no libc calls).
- Follow the System V AMD64 ABI: preserve `%rbx`, `%rbp`, `%r12`–`%r15` and `%rsp`, keep `%rsp` 16-byte aligned at every `call`, and return with the direction flag clear.

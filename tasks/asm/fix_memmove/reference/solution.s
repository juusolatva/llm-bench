# void *buf_move(void *dst, const void *src, size_t n)
        .text
        .globl  buf_move
buf_move:
        movq    %rdi, %rax
        testq   %rdx, %rdx
        je      .Ldone
        cmpq    %rsi, %rdi
        ja      .Lbackward
.Lforward:
        movb    (%rsi), %cl
        movb    %cl, (%rdi)
        incq    %rsi
        incq    %rdi
        decq    %rdx
        jnz     .Lforward
        ret
.Lbackward:
        leaq    -1(%rsi,%rdx), %rsi
        leaq    -1(%rdi,%rdx), %rdi
        movq    %rdx, %rcx
        std
        rep movsb
        cld
.Ldone:
        ret

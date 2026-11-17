# uint64_t sum_above(const uint8_t *a, size_t n, uint8_t threshold)
        .text
        .globl  sum_above
        .type   sum_above, @function
sum_above:
        xorl    %eax, %eax
        testq   %rsi, %rsi
        je      .Ldone
        movzbl  %dl, %edx
.Lloop:
        movzbl  (%rdi), %ecx
        cmpl    %edx, %ecx
        jbe     .Lnext
        addq    %rcx, %rax
.Lnext:
        incq    %rdi
        decq    %rsi
        jne     .Lloop
.Ldone:
        ret
        .size   sum_above, .-sum_above

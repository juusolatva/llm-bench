# int parse_u64(const char *s, size_t n, uint64_t *out)
        .text
        .globl  parse_u64
        .type   parse_u64, @function
parse_u64:
        testq   %rsi, %rsi
        je      .Lfail
        movq    %rdx, %r8               # out (mulq overwrites %rdx)
        movl    $10, %r9d
        xorl    %eax, %eax              # value so far
.Lloop:
        movzbl  (%rdi), %ecx
        subl    $'0', %ecx
        cmpl    $9, %ecx                # unsigned: bytes below '0' wrap to large values
        ja      .Lfail
        mulq    %r9                     # %rdx:%rax = value * 10, CF set if it doesn't fit in 64 bits
        jc      .Lfail
        addq    %rcx, %rax
        jc      .Lfail
        incq    %rdi
        decq    %rsi
        jne     .Lloop
        movq    %rax, (%r8)
        xorl    %eax, %eax
        ret
.Lfail:
        movl    $-1, %eax
        ret
        .size   parse_u64, .-parse_u64

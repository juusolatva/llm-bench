# void stable_sort(uint64_t *a, size_t n, uint64_t *tmp, int (*less)(uint64_t x, uint64_t y))
# Bottom-up merge sort that merges runs of width 1, 2, 4, ... back and forth between a and tmp.
        .text
        .globl  stable_sort
        .type   stable_sort, @function
stable_sort:
        cmpq    $1, %rsi
        jbe     .Lreturn                # n <= 1: already sorted
        pushq   %rbx
        pushq   %rbp
        pushq   %r12
        pushq   %r13
        pushq   %r14
        pushq   %r15
        subq    $56, %rsp               # 6 pushes + 56 bytes: %rsp is 16-byte aligned again
        movq    %rdi, 0(%rsp)           # a
        movq    %rsi, 8(%rsp)           # n
        movq    %rcx, 24(%rsp)          # less
        movq    %rdi, %rbx              # src = a
        movq    %rdx, %rbp              # dst = tmp
        movq    $1, 32(%rsp)            # width = 1
.Lpass:
        movq    $0, 40(%rsp)            # lo = 0
.Lrun:
        movq    40(%rsp), %r12          # i = lo
        movq    %r12, %r14              # k = lo
        movq    32(%rsp), %rax
        movq    8(%rsp), %rcx
        leaq    (%r12,%rax), %r15       # mid = min(lo + width, n)
        cmpq    %rcx, %r15
        cmova   %rcx, %r15
        leaq    (%r15,%rax), %rdx       # hi = min(mid + width, n)
        cmpq    %rcx, %rdx
        cmova   %rcx, %rdx
        movq    %rdx, 48(%rsp)
        movq    %r15, %r13              # j = mid
.Lmerge:
        cmpq    %r15, %r12              # left run used up?
        jae     .Lrest_right
        cmpq    48(%rsp), %r13          # right run used up?
        jae     .Lrest_left
        movq    (%rbx,%r13,8), %rdi     # less(src[j], src[i]): take the right element only if it is
        movq    (%rbx,%r12,8), %rsi     # strictly smaller, so ties keep their order
        call    *24(%rsp)
        testl   %eax, %eax
        jnz     .Ltake_right
        movq    (%rbx,%r12,8), %rax
        movq    %rax, (%rbp,%r14,8)
        incq    %r12
        incq    %r14
        jmp     .Lmerge
.Ltake_right:
        movq    (%rbx,%r13,8), %rax
        movq    %rax, (%rbp,%r14,8)
        incq    %r13
        incq    %r14
        jmp     .Lmerge
.Lrest_left:
        cmpq    %r15, %r12
        jae     .Lrun_done
        movq    (%rbx,%r12,8), %rax
        movq    %rax, (%rbp,%r14,8)
        incq    %r12
        incq    %r14
        jmp     .Lrest_left
.Lrest_right:
        cmpq    48(%rsp), %r13
        jae     .Lrun_done
        movq    (%rbx,%r13,8), %rax
        movq    %rax, (%rbp,%r14,8)
        incq    %r13
        incq    %r14
        jmp     .Lrest_right
.Lrun_done:
        movq    48(%rsp), %rax          # lo = hi
        movq    %rax, 40(%rsp)
        cmpq    8(%rsp), %rax
        jb      .Lrun
        xchgq   %rbx, %rbp              # the merged runs are the next pass's input
        movq    32(%rsp), %rax
        addq    %rax, %rax
        movq    %rax, 32(%rsp)
        cmpq    8(%rsp), %rax
        jb      .Lpass
        cmpq    0(%rsp), %rbx           # sorted data in tmp: copy it back to a
        je      .Ldone
        movq    8(%rsp), %rcx
        xorl    %eax, %eax
.Lcopy:
        movq    (%rbx,%rax,8), %rdx
        movq    %rdx, (%rbp,%rax,8)
        incq    %rax
        cmpq    %rcx, %rax
        jb      .Lcopy
.Ldone:
        addq    $56, %rsp
        popq    %r15
        popq    %r14
        popq    %r13
        popq    %r12
        popq    %rbp
        popq    %rbx
.Lreturn:
        ret
        .size   stable_sort, .-stable_sort

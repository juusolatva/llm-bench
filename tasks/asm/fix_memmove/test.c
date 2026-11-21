#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

/* harness_call(a0, a1, a2, a3) calls harness_fn with a0..a3 in %rdi, %rsi, %rdx and %rcx, the way C code would but
   with distinct sentinels in the callee-saved registers, junk in every other register, the direction flag clear and
   %rsp 16-byte aligned. It records the callee-saved registers, %rsp and the flags right after the return, then
   restores C's registers, so a solution that corrupts them still gets a report instead of a crash. */
uint64_t harness_call(uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3);
void *harness_fn;
const uint64_t harness_sentinel[6] = {
    0x5b5b0b0bc0de0103u, 0x5b5b0b0bc0de0205u, 0x5b5b0b0bc0de0c07u,
    0x5b5b0b0bc0de0d09u, 0x5b5b0b0bc0de0e0bu, 0x5b5b0b0bc0de0f0du,
};
uint64_t harness_c_regs[7];
uint64_t harness_after[6];
uint64_t harness_rsp_before, harness_rsp_after, harness_flags;
uint64_t harness_xmm_junk[32] = {
    0x0123456789abcdefu, 0xfedcba9876543210u, 0x1111111111111111u, 0xeeeeeeeeeeeeeeeeu,
    0x2222222222222222u, 0xddddddddddddddddu, 0x3333333333333333u, 0xccccccccccccccccu,
    0x4444444444444444u, 0xbbbbbbbbbbbbbbbbu, 0x5555555555555555u, 0xaaaaaaaaaaaaaaaau,
    0x6666666666666666u, 0x9999999999999999u, 0x7777777777777777u, 0x8888888888888888u,
    0x8080808080808080u, 0x7f7f7f7f7f7f7f7fu, 0xffffffffffffffffu, 0x0101010101010101u,
    0xa5a5a5a5a5a5a5a5u, 0x5a5a5a5a5a5a5a5au, 0x3c3c3c3c3c3c3c3cu, 0xc3c3c3c3c3c3c3c3u,
    0x0f0f0f0f0f0f0f0fu, 0xf0f0f0f0f0f0f0f0u, 0x1234123412341234u, 0x4321432143214321u,
    0xdeadbeefdeadbeefu, 0xbeefdeadbeefdeadu, 0xcafebabecafebabeu, 0xbabecafebabecafeu,
};
uint64_t harness_stack[64];
__asm__(
    ".pushsection .text\n"
    ".globl harness_call\n"
    ".type harness_call, @function\n"
    "harness_call:\n"
    "    movq %rbx, harness_c_regs+0(%rip)\n"
    "    movq %rbp, harness_c_regs+8(%rip)\n"
    "    movq %r12, harness_c_regs+16(%rip)\n"
    "    movq %r13, harness_c_regs+24(%rip)\n"
    "    movq %r14, harness_c_regs+32(%rip)\n"
    "    movq %r15, harness_c_regs+40(%rip)\n"
    "    movq %rsp, harness_c_regs+48(%rip)\n"
    "    subq $8, %rsp\n"
    "    movq %rsp, harness_rsp_before(%rip)\n"
    "    movq harness_sentinel+0(%rip), %rbx\n"
    "    movq harness_sentinel+8(%rip), %rbp\n"
    "    movq harness_sentinel+16(%rip), %r12\n"
    "    movq harness_sentinel+24(%rip), %r13\n"
    "    movq harness_sentinel+32(%rip), %r14\n"
    "    movq harness_sentinel+40(%rip), %r15\n"
    "    movdqu harness_xmm_junk+0(%rip), %xmm0\n"
    "    movdqu harness_xmm_junk+16(%rip), %xmm1\n"
    "    movdqu harness_xmm_junk+32(%rip), %xmm2\n"
    "    movdqu harness_xmm_junk+48(%rip), %xmm3\n"
    "    movdqu harness_xmm_junk+64(%rip), %xmm4\n"
    "    movdqu harness_xmm_junk+80(%rip), %xmm5\n"
    "    movdqu harness_xmm_junk+96(%rip), %xmm6\n"
    "    movdqu harness_xmm_junk+112(%rip), %xmm7\n"
    "    movdqu harness_xmm_junk+128(%rip), %xmm8\n"
    "    movdqu harness_xmm_junk+144(%rip), %xmm9\n"
    "    movdqu harness_xmm_junk+160(%rip), %xmm10\n"
    "    movdqu harness_xmm_junk+176(%rip), %xmm11\n"
    "    movdqu harness_xmm_junk+192(%rip), %xmm12\n"
    "    movdqu harness_xmm_junk+208(%rip), %xmm13\n"
    "    movdqu harness_xmm_junk+224(%rip), %xmm14\n"
    "    movdqu harness_xmm_junk+240(%rip), %xmm15\n"
    "    movabsq $0x6a756e6b00726178, %rax\n"
    "    movabsq $0x6a756e6b0000ff08, %r8\n"
    "    movabsq $0x6a756e6b0000ff09, %r9\n"
    "    movabsq $0x6a756e6b0000ff10, %r10\n"
    "    movabsq $0x6a756e6b0000ff11, %r11\n"
    "    cld\n"
    "    call *harness_fn(%rip)\n"
    "    movq %rsp, harness_rsp_after(%rip)\n"
    "    leaq harness_stack+512(%rip), %rsp\n"
    "    pushfq\n"
    "    cld\n"
    "    popq harness_flags(%rip)\n"
    "    movq %rbx, harness_after+0(%rip)\n"
    "    movq %rbp, harness_after+8(%rip)\n"
    "    movq %r12, harness_after+16(%rip)\n"
    "    movq %r13, harness_after+24(%rip)\n"
    "    movq %r14, harness_after+32(%rip)\n"
    "    movq %r15, harness_after+40(%rip)\n"
    "    movq harness_c_regs+48(%rip), %rsp\n"
    "    movq harness_c_regs+0(%rip), %rbx\n"
    "    movq harness_c_regs+8(%rip), %rbp\n"
    "    movq harness_c_regs+16(%rip), %r12\n"
    "    movq harness_c_regs+24(%rip), %r13\n"
    "    movq harness_c_regs+32(%rip), %r14\n"
    "    movq harness_c_regs+40(%rip), %r15\n"
    "    ret\n"
    ".size harness_call, .-harness_call\n"
    ".popsection\n");
#define HARNESS_JUNK 0x6a756e6b6a756e6bu /* for argument registers the function doesn't use */

static const char *const harness_reg_names[6] = {"%rbx", "%rbp", "%r12", "%r13", "%r14", "%r15"};
static FILE *harness_err;      /* where case children print failures (stderr, kept when stderr is silenced) */
static char harness_desc[600]; /* the call of the current case, as written in C */
static char harness_want[600]; /* its expected result */

/* Prints the ABI violations of the last harness_call and returns how many there were. */
static int harness_abi_report(void) {
    int n = 0;
    for (int i = 0; i < 6; i++)
        if (harness_after[i] != harness_sentinel[i]) {
            fprintf(harness_err, "FAIL: %s: %s not preserved: 0x%016" PRIx64 " after the return, want 0x%016" PRIx64 "\n",
                    harness_desc, harness_reg_names[i], harness_after[i], harness_sentinel[i]);
            n++;
        }
    if (harness_rsp_after != harness_rsp_before) {
        fprintf(harness_err, "FAIL: %s: %%rsp changed by %" PRId64 " bytes across the call, want 0\n", harness_desc,
                (int64_t)(harness_rsp_after - harness_rsp_before));
        n++;
    }
    if (harness_flags & 0x400) {
        fprintf(harness_err, "FAIL: %s: returned with the direction flag set, want it clear\n", harness_desc);
        n++;
    }
    return n;
}

#define HARNESS_MAX_FAILS 10
static int harness_fails, harness_crashes, harness_stopped, harness_verdict_fd = -1;
static size_t harness_page;

static void harness_alloc_failed(void) {
    fputs("harness: allocation failed\n", harness_err ? harness_err : stderr); /* stderr is silenced after a crash */
    if (harness_verdict_fd >= 0 && write(harness_verdict_fd, "A", 1) == 1) _exit(0);
    exit(1);
}

static void *harness_malloc(size_t n) {
    void *p = malloc(n ? n : 1);
    if (!p) harness_alloc_failed();
    return p;
}

enum { HARNESS_AT_END, HARNESS_AT_START };
/* len writable bytes that end right before an inaccessible page (HARNESS_AT_END) or start right after one
   (HARNESS_AT_START). For len 0, a pointer into the inaccessible page. Used in case children only, never freed. */
static unsigned char *harness_guarded(size_t len, int where) {
    size_t pages = (len + harness_page - 1) / harness_page;
    unsigned char *base = mmap(NULL, (pages + 1) * harness_page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS,
                               -1, 0);
    if (base == MAP_FAILED) harness_alloc_failed();
    if (where == HARNESS_AT_END) {
        if (mprotect(base + pages * harness_page, harness_page, PROT_NONE)) harness_alloc_failed();
        return base + pages * harness_page - len;
    }
    if (mprotect(base, harness_page, PROT_NONE)) harness_alloc_failed();
    return len ? base + harness_page : base;
}

__attribute__((unused)) static const char *harness_where(int where) {
    return where == HARNESS_AT_END ? "ending right before an inaccessible page"
                                   : "starting right after an inaccessible page";
}

/* Runs body(ctx) for the case described by harness_desc and harness_want in a child process, with a time limit of
   limit_s seconds. body returns 1 if the case passed; otherwise it has printed "FAIL: ..." lines. The child reports
   its verdict through a pipe, so a child that ends before body returns (an exit system call in the solution) fails
   even with exit status 0. After the first crash, children silence stderr so later sanitizer reports don't crowd
   out the rest of the output. Stops all further cases after the first timeout or HARNESS_MAX_FAILS failures. */
static void harness_run(int (*body)(const void *), const void *ctx, int limit_s, const char *timeout_msg) {
    if (harness_stopped) return;
    int fds[2];
    fflush(NULL);
    if (pipe(fds)) { perror("harness: pipe"); exit(1); }
    pid_t pid = fork();
    if (pid < 0) { perror("harness: fork"); exit(1); }
    if (pid == 0) {
        close(fds[0]);
        harness_verdict_fd = fds[1];
        if (harness_crashes) {
            int keep = dup(2), null = open("/dev/null", O_WRONLY);
            FILE *err = keep >= 0 ? fdopen(keep, "w") : NULL;
            if (err && null >= 0 && dup2(null, 2) >= 0) {
                setvbuf(err, NULL, _IONBF, 0);
                harness_err = err;
            }
        }
        char verdict = body(ctx) ? 'P' : 'F';
        fflush(NULL);
        if (write(fds[1], &verdict, 1) != 1) _exit(1);
        _exit(0);
    }
    close(fds[1]);
    char verdict = 0;
    struct pollfd p = {.fd = fds[0], .events = POLLIN};
    int ready;
    do ready = poll(&p, 1, limit_s * 1000);
    while (ready < 0 && errno == EINTR);
    if (ready > 0) {
        if (read(fds[0], &verdict, 1) != 1) verdict = 0;
    } else {
        kill(pid, SIGKILL);
    }
    close(fds[0]);
    int status;
    while (waitpid(pid, &status, 0) < 0)
        if (errno != EINTR) { perror("harness: waitpid"); exit(1); }
    if (verdict == 'A') exit(1);
    if (verdict == 'P' && WIFEXITED(status) && WEXITSTATUS(status) == 0) return;
    if (verdict != 'F') {
        if (ready <= 0) {
            if (timeout_msg) fprintf(stderr, "FAIL: %s\n", timeout_msg);
            else fprintf(stderr, "FAIL: %s: timed out after %d s (infinite loop?), want %s\n", harness_desc, limit_s,
                         harness_want);
            fputs("harness: stopping after the first timeout\n", stderr);
            harness_stopped = 1;
        } else if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
            fprintf(stderr, "FAIL: %s: the process ended before the function returned (exit system call?), want %s\n",
                    harness_desc, harness_want);
        } else if (WIFSIGNALED(status)) {
            fprintf(stderr, "FAIL: %s: crashed with signal %d (%s), want %s\n", harness_desc, WTERMSIG(status),
                    strsignal(WTERMSIG(status)), harness_want);
            harness_crashes++;
        } else {
            fprintf(stderr, "FAIL: %s: crashed (%s), want %s\n", harness_desc,
                    harness_crashes ? "report not repeated after the first crash" : "see the report above",
                    harness_want);
            harness_crashes++;
        }
    }
    if (++harness_fails >= HARNESS_MAX_FAILS && !harness_stopped) {
        fprintf(stderr, "harness: stopping after %d failures\n", HARNESS_MAX_FAILS);
        harness_stopped = 1;
    }
}

/* Writes "{1, 2, 3}" for the first n bytes of a (at most 24, then "..."). */
__attribute__((unused)) static void harness_fmt_bytes(char *buf, size_t size, const unsigned char *a, size_t n) {
    size_t len = (size_t)snprintf(buf, size, "{");
    for (size_t i = 0; i < n && i < 24 && len < size; i++)
        len += (size_t)snprintf(buf + len, size - len, "%s%u", i ? ", " : "", a[i]);
    if (len < size) snprintf(buf + len, size - len, "%s}", n > 24 ? ", ..." : "");
}

static void harness_init(void) {
    harness_page = (size_t)sysconf(_SC_PAGESIZE);
    harness_err = stderr;
    setvbuf(stdout, NULL, _IOLBF, 0);
}

static int harness_finish(void) {
    if (harness_fails) {
        fprintf(stderr, "harness: %d case(s) failed%s\n", harness_fails, harness_stopped ? " (stopped early)" : "");
        return 1;
    }
    puts("harness: all checks passed");
    return 0;
}

void *buf_move(void *dst, const void *src, size_t n);

enum { HARNESS_CANARY_LEN = 16, HARNESS_CANARY = 0xcc };
enum {
    HARNESS_NULLS,        /* n == 0, dst == src == NULL */
    HARNESS_INACCESSIBLE, /* n == 0, dst and src point into inaccessible pages */
    HARNESS_SPAN,         /* dst and src in one buffer p: dst = p + dst_off, src = p + src_off */
    HARNESS_DISJOINT,     /* dst and src in separate buffers */
};
typedef struct {
    int kind;
    size_t n, dst_off, src_off; /* HARNESS_SPAN */
    int dst_above;              /* HARNESS_INACCESSIBLE, HARNESS_DISJOINT: dst at the higher address */
    int where;                  /* placement of the buffers */
} harness_mm_case;

/* A data byte that is neither the canary nor the low byte of the %rbx sentinel. */
static unsigned char harness_mm_byte(size_t i) {
    unsigned char b = (unsigned char)(i * 37 + 0x41);
    return b == HARNESS_CANARY || b == (unsigned char)harness_sentinel[0] ? (unsigned char)(b + 1) : b;
}

/* span bytes of data with HARNESS_CANARY_LEN canary bytes on the side without the inaccessible page. Returns the
   start of the canary-to-canary block in *block and its length in *block_len. */
static unsigned char *harness_mm_buffer(size_t span, int where, size_t seed, unsigned char **block, size_t *block_len) {
    *block_len = span + HARNESS_CANARY_LEN;
    *block = harness_guarded(*block_len, where);
    memset(*block, HARNESS_CANARY, *block_len);
    unsigned char *p = where == HARNESS_AT_END ? *block + HARNESS_CANARY_LEN : *block;
    for (size_t i = 0; i < span; i++) p[i] = harness_mm_byte(seed + i);
    return p;
}

/* Reports the first difference between the block and its expected contents, naming the position relative to dst
   and saying whether it lies inside dst[0..n-1]. Returns 1 if there was one. */
static int harness_mm_compare(const unsigned char *block, const unsigned char *want, size_t len,
                              const unsigned char *dst, size_t n, const char *what) {
    size_t i = 0;
    while (i < len && block[i] == want[i]) i++;
    if (i == len) return 0;
    ptrdiff_t pos = (block + i) - dst;
    if (pos >= 0 && (size_t)pos < n) {
        size_t from = (size_t)pos >= 3 ? (size_t)pos - 3 : 0, to = from + 8 < n ? from + 8 : n;
        char got_s[100], want_s[100];
        harness_fmt_bytes(got_s, sizeof got_s, dst + from, to - from);
        harness_fmt_bytes(want_s, sizeof want_s, want + (dst - block) + from, to - from);
        fprintf(harness_err, "FAIL: %s: wrong bytes in dst; first at dst[%td]: dst[%zu..%zu] = %s afterwards, want %s\n",
                harness_desc, pos, from, to - 1, got_s, want_s);
    } else if (n == 0) {
        fprintf(harness_err, "FAIL: %s: %s the byte at dst[%td] (n is 0, so no byte may change): 0x%02x afterwards, "
                "was 0x%02x\n", harness_desc, what, pos, block[i], want[i]);
    } else {
        fprintf(harness_err, "FAIL: %s: %s the byte at dst[%td] (outside dst[0..%zu]): 0x%02x afterwards, was 0x%02x\n",
                harness_desc, what, pos, n - 1, block[i], want[i]);
    }
    return 1;
}

static int harness_mm_body(const void *ctx) {
    const harness_mm_case *c = ctx;
    unsigned char *dst = NULL, *src = NULL, *block = NULL, *block2 = NULL, *want = NULL, *want2 = NULL;
    size_t len = 0, len2 = 0;
    if (c->kind == HARNESS_INACCESSIBLE) {
        dst = harness_guarded(0, HARNESS_AT_END);
        src = harness_guarded(0, HARNESS_AT_END);
        if (((uintptr_t)dst > (uintptr_t)src) != c->dst_above) { unsigned char *t = dst; dst = src; src = t; }
    } else if (c->kind == HARNESS_SPAN) {
        size_t span = (c->dst_off > c->src_off ? c->dst_off : c->src_off) + c->n;
        unsigned char *p = harness_mm_buffer(span, c->where, 0, &block, &len);
        dst = p + c->dst_off;
        src = p + c->src_off;
        want = harness_malloc(len);
        memcpy(want, block, len);
        memmove(want + (dst - block), want + (src - block), c->n);
    } else if (c->kind == HARNESS_DISJOINT) {
        dst = harness_mm_buffer(c->n, c->where, 100, &block, &len);
        src = harness_mm_buffer(c->n, c->where, 0, &block2, &len2);
        if (((uintptr_t)dst > (uintptr_t)src) != c->dst_above) {
            unsigned char *t = dst; dst = src; src = t;
            t = block; block = block2; block2 = t;
            size_t l = len; len = len2; len2 = l;
            for (size_t i = 0; i < c->n; i++) { dst[i] = harness_mm_byte(100 + i); src[i] = harness_mm_byte(i); }
        }
        want = harness_malloc(len);
        memcpy(want, block, len);
        memcpy(want + (dst - block), src, c->n);
        want2 = harness_malloc(len2);
        memcpy(want2, block2, len2);
    }
    uint64_t got = harness_call((uint64_t)(uintptr_t)dst, (uint64_t)(uintptr_t)src, c->n, HARNESS_JUNK);
    int ok = 1;
    if (got != (uint64_t)(uintptr_t)dst) {
        int64_t off = (int64_t)(got - (uint64_t)(uintptr_t)dst);
        fprintf(harness_err, "FAIL: %s returned dst %c %" PRIu64 ", want dst\n", harness_desc, off < 0 ? '-' : '+',
                off < 0 ? -(uint64_t)off : (uint64_t)off);
        ok = 0;
    }
    if (harness_abi_report()) ok = 0;
    if (block && harness_mm_compare(block, want, len, dst, c->n, c->kind == HARNESS_SPAN ? "changed" : "wrote"))
        ok = 0;
    if (block2) {
        size_t i = 0;
        while (i < len2 && block2[i] == want2[i]) i++;
        if (i < len2) {
            fprintf(harness_err, "FAIL: %s: changed the byte at src[%td]\n", harness_desc, (block2 + i) - src);
            ok = 0;
        }
    }
    return ok;
}

static void harness_mm(harness_mm_case c) {
    const char *where = harness_where(c.where);
    switch (c.kind) {
    case HARNESS_NULLS:
        snprintf(harness_desc, sizeof harness_desc, "buf_move(dst = NULL, src = NULL, n = 0)");
        break;
    case HARNESS_INACCESSIBLE:
        snprintf(harness_desc, sizeof harness_desc, "buf_move(dst, src, n = 0) with dst and src pointing into "
                 "inaccessible pages, dst %s src", c.dst_above ? ">" : "<");
        break;
    case HARNESS_SPAN:
        snprintf(harness_desc, sizeof harness_desc, "buf_move(dst = p + %zu, src = p + %zu, n = %zu) with p[0..%zu] "
                 "%s", c.dst_off, c.src_off, c.n,
                 (c.dst_off > c.src_off ? c.dst_off : c.src_off) + c.n - 1, where);
        break;
    default:
        snprintf(harness_desc, sizeof harness_desc, "buf_move(dst, src, n = %zu) with dst and src in separate buffers "
                 "(dst %s src), each %s", c.n, c.dst_above ? ">" : "<", where);
    }
    snprintf(harness_want, sizeof harness_want, "dst[0..n-1] = the original src[0..n-1], nothing else changed, "
             "dst returned");
    harness_run(harness_mm_body, &c, 2, NULL);
}

int main(void) {
    harness_init();
    harness_fn = (void *)buf_move;
    int flip = 0;
    harness_mm((harness_mm_case){.kind = HARNESS_NULLS});
    for (int above = 0; above < 2; above++)
        harness_mm((harness_mm_case){.kind = HARNESS_INACCESSIBLE, .dst_above = above});
    for (int where = HARNESS_AT_END; where <= HARNESS_AT_START; where++) {
        harness_mm((harness_mm_case){.kind = HARNESS_SPAN, .n = 0, .dst_off = 0, .src_off = 5, .where = where});
        harness_mm((harness_mm_case){.kind = HARNESS_SPAN, .n = 0, .dst_off = 5, .src_off = 5, .where = where});
        harness_mm((harness_mm_case){.kind = HARNESS_SPAN, .n = 0, .dst_off = 5, .src_off = 0, .where = where});
    }
    static const size_t sizes[] = {1, 3, 7, 8, 9, 15, 16, 17, 64, 257};
    for (size_t s = 0; s < sizeof sizes / sizeof *sizes; s++)
        for (int above = 0; above < 2; above++, flip ^= 1)
            harness_mm((harness_mm_case){.kind = HARNESS_DISJOINT, .n = sizes[s], .dst_above = above, .where = flip});
    static const size_t offsets[] = {1, 3, 7, 8, 9, 15, 16, 17};
    static const size_t lengths[] = {20, 64, 257};
    for (size_t o = 0; o < sizeof offsets / sizeof *offsets; o++)
        for (size_t l = 0; l < sizeof lengths / sizeof *lengths; l++, flip ^= 1) {
            harness_mm((harness_mm_case){.kind = HARNESS_SPAN, .n = lengths[l], .dst_off = offsets[o], .where = flip});
            harness_mm((harness_mm_case){.kind = HARNESS_SPAN, .n = lengths[l], .src_off = offsets[o], .where = !flip});
        }
    static const size_t same[] = {1, 16, 100};
    for (size_t s = 0; s < sizeof same / sizeof *same; s++, flip ^= 1)
        harness_mm((harness_mm_case){.kind = HARNESS_SPAN, .n = same[s], .dst_off = 4, .src_off = 4, .where = flip});
    static const size_t adjacent[] = {8, 33};
    for (size_t s = 0; s < sizeof adjacent / sizeof *adjacent; s++, flip ^= 1) {
        harness_mm((harness_mm_case){.kind = HARNESS_SPAN, .n = adjacent[s], .dst_off = adjacent[s], .where = flip});
        harness_mm((harness_mm_case){.kind = HARNESS_SPAN, .n = adjacent[s], .src_off = adjacent[s], .where = !flip});
    }
    return harness_finish();
}

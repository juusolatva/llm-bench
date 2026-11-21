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

void stable_sort(uint64_t *a, size_t n, uint64_t *tmp, int (*less)(uint64_t x, uint64_t y));

/* harness_less is the comparator passed to stable_sort. It records %rsp and the flags at entry, calls
   harness_less_check(x, y) on an aligned stack and returns its result, then clobbers every caller-saved register,
   sets the flags to the opposite of the result's zero test, and fills its red zone (which overlaps the caller's)
   with junk. harness_less_check returns the int result in the low 32 bits and junk in the upper 32. */
int harness_less(uint64_t x, uint64_t y);
uint64_t harness_less_check(uint64_t x, uint64_t y);
uint64_t harness_less_rsp, harness_less_flags;
__asm__(
    ".pushsection .text\n"
    ".globl harness_less\n"
    ".type harness_less, @function\n"
    "harness_less:\n"
    "    pushfq\n"
    "    movq %rsp, harness_less_rsp(%rip)\n"
    "    popq harness_less_flags(%rip)\n"
    "    cld\n"
    "    pushq %rbx\n"
    "    movq %rsp, %rbx\n"
    "    andq $-16, %rsp\n"
    "    call harness_less_check\n"
    "    movq %rbx, %rsp\n"
    "    popq %rbx\n"
    "    xorl %ecx, %ecx\n"
    "    testl %eax, %eax\n"
    "    sete %cl\n"
    "    testl %ecx, %ecx\n"
    "    movabsq $0x6a756e6b0000c001, %rcx\n"
    "    movabsq $0x6a756e6b0000c002, %rdx\n"
    "    movabsq $0x6a756e6b0000c003, %rsi\n"
    "    movabsq $0x6a756e6b0000c004, %rdi\n"
    "    movabsq $0x6a756e6b0000c005, %r8\n"
    "    movabsq $0x6a756e6b0000c006, %r9\n"
    "    movabsq $0x6a756e6b0000c007, %r10\n"
    "    movabsq $0x6a756e6b0000c008, %r11\n"
    "    movdqu harness_xmm_junk+8(%rip), %xmm0\n"
    "    movdqu harness_xmm_junk+24(%rip), %xmm1\n"
    "    movdqu harness_xmm_junk+40(%rip), %xmm2\n"
    "    movdqu harness_xmm_junk+56(%rip), %xmm3\n"
    "    movdqu harness_xmm_junk+72(%rip), %xmm4\n"
    "    movdqu harness_xmm_junk+88(%rip), %xmm5\n"
    "    movdqu harness_xmm_junk+104(%rip), %xmm6\n"
    "    movdqu harness_xmm_junk+120(%rip), %xmm7\n"
    "    movdqu harness_xmm_junk+136(%rip), %xmm8\n"
    "    movdqu harness_xmm_junk+152(%rip), %xmm9\n"
    "    movdqu harness_xmm_junk+168(%rip), %xmm10\n"
    "    movdqu harness_xmm_junk+184(%rip), %xmm11\n"
    "    movdqu harness_xmm_junk+200(%rip), %xmm12\n"
    "    movdqu harness_xmm_junk+216(%rip), %xmm13\n"
    "    movdqu harness_xmm_junk+232(%rip), %xmm14\n"
    "    movdqu harness_xmm_junk+136(%rip), %xmm15\n"
    "    movq %rdi, -8(%rsp)\n"
    "    movq %rsi, -16(%rsp)\n"
    "    movq %rdx, -24(%rsp)\n"
    "    movq %rcx, -32(%rsp)\n"
    "    movq %r8, -40(%rsp)\n"
    "    movq %r9, -48(%rsp)\n"
    "    movq %r10, -56(%rsp)\n"
    "    movq %r11, -64(%rsp)\n"
    "    movq %rdi, -72(%rsp)\n"
    "    movq %rsi, -80(%rsp)\n"
    "    movq %rdx, -88(%rsp)\n"
    "    movq %rcx, -96(%rsp)\n"
    "    movq %r8, -104(%rsp)\n"
    "    movq %r9, -112(%rsp)\n"
    "    movq %r10, -120(%rsp)\n"
    "    movq %r11, -128(%rsp)\n"
    "    ret\n"
    ".size harness_less, .-harness_less\n"
    ".popsection\n");

enum { HARNESS_ASC, HARNESS_DESC };
enum { HARNESS_NULL = 2, HARNESS_INACCESSIBLE = 3 };
#define HARNESS_TIMING_N 1000000
typedef struct {
    const uint64_t *input; /* NULL for the timing case, which generates its input in the child */
    size_t n;
    int order;             /* HARNESS_ASC or HARNESS_DESC: how less orders the keys */
    int where;             /* placement of a and tmp */
    const char *gen;       /* how the input was generated, for n > 16 */
} harness_ss_case;

/* State of the current case child, for harness_less_check. */
static const uint64_t *harness_ss_input;
static size_t harness_ss_n;
static int harness_ss_order;
static uint64_t harness_ss_calls, harness_ss_bound, harness_ss_bad_arg_call, harness_ss_bad_arg;
static uint64_t harness_ss_misaligned_call, harness_ss_misaligned_by, harness_ss_df_call;

static uint64_t harness_ss_elem(uint32_t index, uint32_t key) { return (uint64_t)index << 32 | key; }
static uint32_t harness_ss_key(uint64_t e) { return (uint32_t)e; }
static uint32_t harness_ss_index(uint64_t e) { return (uint32_t)(e >> 32); }

static uint64_t harness_ss_log_bound(size_t n) {
    unsigned log = 0;
    while (log < 64 && ((size_t)1 << log) < n) log++;
    return (uint64_t)n * log;
}

uint64_t harness_less_check(uint64_t x, uint64_t y) {
    uint64_t call = ++harness_ss_calls;
    if (call > harness_ss_bound) {
        fprintf(harness_err, "FAIL: %s: too many comparisons: more than n*ceil(log2(n)) = %" PRIu64
                " calls to less for n = %zu\n", harness_desc, harness_ss_bound, harness_ss_n);
        fflush(NULL);
        if (write(harness_verdict_fd, "F", 1) != 1) _exit(1);
        _exit(0);
    }
    if ((harness_less_rsp & 15) && !harness_ss_misaligned_call) {
        harness_ss_misaligned_call = call;
        harness_ss_misaligned_by = harness_less_rsp & 15;
    }
    if ((harness_less_flags & 0x400) && !harness_ss_df_call) harness_ss_df_call = call;
    uint64_t args[2] = {x, y};
    for (int i = 0; i < 2; i++) {
        uint32_t index = harness_ss_index(args[i]);
        if ((index >= harness_ss_n || harness_ss_input[index] != args[i]) && !harness_ss_bad_arg_call) {
            harness_ss_bad_arg_call = call;
            harness_ss_bad_arg = args[i];
        }
    }
    int result = harness_ss_order == HARNESS_ASC ? harness_ss_key(x) < harness_ss_key(y)
                                                 : harness_ss_key(x) > harness_ss_key(y);
    static const uint32_t trues[3] = {1, 0xffffffffu, 0x100};
    uint64_t junk = (0xa5a5a5a5u ^ (uint32_t)call) | 1;
    return junk << 32 | (result ? trues[call % 3] : 0);
}

static int harness_ss_cmp_asc(const void *p, const void *q) {
    uint64_t x = *(const uint64_t *)p, y = *(const uint64_t *)q;
    uint32_t kx = harness_ss_key(x), ky = harness_ss_key(y);
    if (kx != ky) return kx < ky ? -1 : 1;
    uint32_t ix = harness_ss_index(x), iy = harness_ss_index(y);
    return (ix > iy) - (ix < iy); /* 0 for an element compared with itself, as qsort requires */
}

static int harness_ss_cmp_desc(const void *p, const void *q) {
    uint64_t x = *(const uint64_t *)p, y = *(const uint64_t *)q;
    uint32_t kx = harness_ss_key(x), ky = harness_ss_key(y);
    if (kx != ky) return kx > ky ? -1 : 1;
    uint32_t ix = harness_ss_index(x), iy = harness_ss_index(y);
    return (ix > iy) - (ix < iy); /* 0 for an element compared with itself, as qsort requires */
}

static void harness_ss_fmt(char *buf, size_t size, const uint64_t *a, size_t n) {
    size_t len = (size_t)snprintf(buf, size, "{");
    for (size_t i = 0; i < n && len < size; i++)
        len += (size_t)snprintf(buf + len, size - len, "%s%" PRIu32 "#%" PRIu32, i ? ", " : "", harness_ss_key(a[i]),
                                harness_ss_index(a[i]));
    if (len < size) snprintf(buf + len, size - len, "}");
}

static uint64_t harness_ss_lcg(uint64_t *state) {
    *state = *state * 6364136223846793005u + 1442695040888963407u;
    return *state >> 33;
}

static int harness_ss_body(const void *ctx) {
    const harness_ss_case *c = ctx;
    size_t n = c->n;
    uint64_t *input = (uint64_t *)c->input;
    if (!input) {
        input = harness_malloc(n * sizeof *input);
        uint64_t state = 42;
        for (size_t i = 0; i < n; i++) input[i] = harness_ss_elem((uint32_t)i, (uint32_t)(harness_ss_lcg(&state) % 1000));
    }
    uint64_t *a = NULL, *tmp = NULL;
    if (c->where == HARNESS_INACCESSIBLE) {
        a = (uint64_t *)harness_guarded(0, HARNESS_AT_END);
        tmp = (uint64_t *)harness_guarded(0, HARNESS_AT_START);
    } else if (c->where != HARNESS_NULL) {
        a = (uint64_t *)harness_guarded(n * sizeof *a, c->where);
        tmp = (uint64_t *)harness_guarded(n * sizeof *tmp, c->where);
        memcpy(a, input, n * sizeof *a);
        for (size_t i = 0; i < n; i++) tmp[i] = 0x7e7e7e7e7e7e7e7eu;
    }
    uint64_t *want = harness_malloc(n * sizeof *want);
    if (n) memcpy(want, input, n * sizeof *want);
    qsort(want, n, sizeof *want, c->order == HARNESS_ASC ? harness_ss_cmp_asc : harness_ss_cmp_desc);
    harness_ss_input = input;
    harness_ss_n = n;
    harness_ss_order = c->order;
    harness_ss_bound = harness_ss_log_bound(n);
    harness_call((uint64_t)(uintptr_t)a, n, (uint64_t)(uintptr_t)tmp, (uint64_t)(uintptr_t)harness_less);
    int ok = 1;
    if (harness_ss_bad_arg_call) {
        fprintf(harness_err, "FAIL: %s: call %" PRIu64 " to less passed 0x%016" PRIx64
                ", which is not an element of the input\n", harness_desc, harness_ss_bad_arg_call, harness_ss_bad_arg);
        ok = 0;
    }
    if (harness_ss_misaligned_call) {
        fprintf(harness_err, "FAIL: %s: %%rsp %% 16 = %" PRIu64 " at call %" PRIu64 " to less, want 0\n", harness_desc,
                harness_ss_misaligned_by, harness_ss_misaligned_call);
        ok = 0;
    }
    if (harness_ss_df_call) {
        fprintf(harness_err, "FAIL: %s: direction flag set at call %" PRIu64 " to less, want it clear\n",
                harness_desc, harness_ss_df_call);
        ok = 0;
    }
    if (harness_abi_report()) ok = 0;
    size_t diff = 0;
    while (diff < n && a[diff] == want[diff]) diff++;
    if (diff < n) {
        char got_s[400], want_s[400];
        if (n <= 16) {
            harness_ss_fmt(got_s, sizeof got_s, a, n);
            harness_ss_fmt(want_s, sizeof want_s, want, n);
            fprintf(harness_err, "FAIL: %s: a = %s afterwards, want %s\n", harness_desc, got_s, want_s);
        } else {
            size_t from = diff >= 2 ? diff - 2 : 0, count = n - from < 5 ? n - from : 5;
            harness_ss_fmt(got_s, sizeof got_s, a + from, count);
            harness_ss_fmt(want_s, sizeof want_s, want + from, count);
            fprintf(harness_err, "FAIL: %s: first wrong element at a[%zu]; a[%zu..%zu] = %s afterwards, want %s\n",
                    harness_desc, diff, from, from + count - 1, got_s, want_s);
        }
        ok = 0;
    }
    return ok;
}

static void harness_ss(const uint64_t *input, size_t n, int order, int where, const char *gen) {
    harness_ss_case c = {input, n, order, where, gen};
    const char *less = order == HARNESS_ASC ? "less = key ascending" : "less = key descending";
    if (where == HARNESS_NULL) {
        snprintf(harness_desc, sizeof harness_desc, "stable_sort(a = NULL, n = 0, tmp = NULL, %s)", less);
    } else if (where == HARNESS_INACCESSIBLE) {
        snprintf(harness_desc, sizeof harness_desc,
                 "stable_sort(a = (pointer into an inaccessible page), n = 0, tmp = (pointer into an inaccessible "
                 "page), %s)", less);
    } else {
        char in[400];
        if (n <= 16) harness_ss_fmt(in, sizeof in, input, n);
        else snprintf(in, sizeof in, "(%s)", gen);
        snprintf(harness_desc, sizeof harness_desc, "stable_sort(a = %s, n = %zu, tmp, %s) with a and tmp each %s", in,
                 n, less, harness_where(where));
    }
    snprintf(harness_want, sizeof harness_want, "a sorted by key %s with ties in input order, at most %" PRIu64
             " calls to less", order == HARNESS_ASC ? "ascending" : "descending", harness_ss_log_bound(n));
    if (!input && n)
        harness_run(harness_ss_body, &c, 20, "too slow: stable_sort of 1000000 elements took more than 20 s; it must "
                    "run in O(n log n) time");
    else
        harness_run(harness_ss_body, &c, 2, NULL);
}

static uint32_t harness_ss_bitrev(uint32_t i, unsigned bits) {
    uint32_t r = 0;
    for (unsigned b = 0; b < bits; b++) r |= ((i >> b) & 1) << (bits - 1 - b);
    return r;
}

static int harness_ss_key_desc(const void *p, const void *q) {
    uint32_t x = *(const uint32_t *)p, y = *(const uint32_t *)q;
    return x < y ? 1 : x > y ? -1 : 0;
}

int main(void) {
    harness_init();
    harness_fn = (void *)stable_sort;
    fputs("harness: elements are shown as key#i, the element at index i of the input; less compares keys\n", stderr);
    for (int order = HARNESS_ASC; order <= HARNESS_DESC; order++) {
        harness_ss(NULL, 0, order, HARNESS_NULL, NULL);
        harness_ss(NULL, 0, order, HARNESS_INACCESSIBLE, NULL);
    }
    static uint64_t buf[4096];
    buf[0] = harness_ss_elem(0, 5);
    harness_ss(buf, 1, HARNESS_ASC, HARNESS_AT_END, NULL);
    harness_ss(buf, 1, HARNESS_DESC, HARNESS_AT_START, NULL);
    static const uint32_t pairs[3][2] = {{1, 2}, {2, 1}, {3, 3}};
    for (int p = 0; p < 3; p++)
        for (int order = HARNESS_ASC; order <= HARNESS_DESC; order++) {
            buf[0] = harness_ss_elem(0, pairs[p][0]);
            buf[1] = harness_ss_elem(1, pairs[p][1]);
            harness_ss(buf, 2, order, order == HARNESS_ASC ? HARNESS_AT_END : HARNESS_AT_START, NULL);
        }
    static const size_t sizes[] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 31, 32, 33, 64, 100, 1000};
    static const char *const patterns[4] = {"keys 0-9 in ascending runs", "keys 0-9 in descending runs",
                                            "all keys equal", "pseudo-random keys 0-9"};
    for (size_t s = 0; s < sizeof sizes / sizeof *sizes; s++)
        for (int pat = 0; pat < 4; pat++)
            for (int order = HARNESS_ASC; order <= HARNESS_DESC; order++) {
                size_t n = sizes[s];
                uint64_t state = 7 + n;
                for (size_t i = 0; i < n; i++) {
                    uint32_t key = pat == 0 ? (uint32_t)(i * 10 / n) : pat == 1 ? (uint32_t)(9 - i * 10 / n)
                                 : pat == 2 ? 4 : (uint32_t)(harness_ss_lcg(&state) % 10);
                    buf[i] = harness_ss_elem((uint32_t)i, key);
                }
                harness_ss(buf, n, order, (pat + order) % 2 ? HARNESS_AT_START : HARNESS_AT_END, patterns[pat]);
            }
    static const size_t adv[2] = {1024, 4096};
    for (int k = 0; k < 2; k++) {
        size_t n = adv[k];
        unsigned bits = k ? 12 : 10;
        uint32_t keys[4096];
        for (size_t i = 0; i < n; i++) keys[i] = harness_ss_bitrev((uint32_t)i, bits);
        for (size_t i = 0; i < n; i++) buf[i] = harness_ss_elem((uint32_t)i, keys[(i & ~(size_t)63) + 63 - (i & 63)]);
        harness_ss(buf, n, HARNESS_ASC, HARNESS_AT_END,
                   k ? "distinct keys 0-4095: key of element i = 12-bit reversal of i, then each block of 64 reversed"
                     : "distinct keys 0-1023: key of element i = 10-bit reversal of i, then each block of 64 reversed");
        for (size_t b = 0; b < n; b += 8) qsort(keys + b, 8, sizeof *keys, harness_ss_key_desc);
        for (size_t i = 0; i < n; i++) buf[i] = harness_ss_elem((uint32_t)i, keys[i]);
        harness_ss(buf, n, HARNESS_ASC, HARNESS_AT_START,
                   k ? "distinct keys 0-4095: key of element i = 12-bit reversal of i, then each block of 8 sorted "
                       "descending"
                     : "distinct keys 0-1023: key of element i = 10-bit reversal of i, then each block of 8 sorted "
                       "descending");
    }
    harness_ss(NULL, HARNESS_TIMING_N, HARNESS_ASC, HARNESS_AT_END, "1000000 pseudo-random keys 0-999");
    return harness_finish();
}

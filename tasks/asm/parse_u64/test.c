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
    fputs("harness: allocation failed\n", stderr);
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

int parse_u64(const char *s, size_t n, uint64_t *out);

enum { HARNESS_NULL = 2, HARNESS_INACCESSIBLE = 3 };
#define HARNESS_OUT_SENTINEL 0x0badc0de0badc0deu
#define HARNESS_CANARY 0xc4c4c4c4c4c4c4c4u
typedef struct {
    const char *src;
    size_t n;
    int where; /* HARNESS_AT_END, HARNESS_AT_START, HARNESS_NULL or HARNESS_INACCESSIBLE */
} harness_pu_case;

/* The expected result: 0 and the value in *value, or -1. */
static int harness_pu_expected(const char *s, size_t n, uint64_t *value) {
    uint64_t v = 0;
    if (n == 0) return -1;
    for (size_t i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c < '0' || c > '9') return -1;
        if (__builtin_mul_overflow(v, 10, &v) || __builtin_add_overflow(v, c - '0', &v)) return -1;
    }
    *value = v;
    return 0;
}

static int harness_pu_body(const void *ctx) {
    const harness_pu_case *c = ctx;
    char *s = NULL;
    if (c->where == HARNESS_INACCESSIBLE) {
        s = (char *)harness_guarded(0, HARNESS_AT_END);
    } else if (c->where != HARNESS_NULL) {
        s = (char *)harness_guarded(c->n, c->where);
        memcpy(s, c->src, c->n);
    }
    uint64_t *box = harness_malloc(3 * sizeof *box);
    box[0] = box[2] = HARNESS_CANARY;
    box[1] = HARNESS_OUT_SENTINEL;
    uint64_t value = HARNESS_OUT_SENTINEL;
    int want = harness_pu_expected(c->src, c->n, &value);
    int got = (int)(uint32_t)harness_call((uint64_t)(uintptr_t)s, c->n, (uint64_t)(uintptr_t)&box[1], HARNESS_JUNK);
    int ok = 1;
    if (got != want) {
        fprintf(harness_err, "FAIL: %s returned %d, want %d\n", harness_desc, got, want);
        ok = 0;
    } else if (box[1] != value) {
        if (want == 0)
            fprintf(harness_err, "FAIL: %s returned 0 and stored %" PRIu64 ", want %" PRIu64 "\n", harness_desc,
                    box[1], value);
        else
            fprintf(harness_err, "FAIL: %s returned -1 but changed *out from %" PRIu64 " to %" PRIu64
                    ", want it unchanged\n", harness_desc, (uint64_t)HARNESS_OUT_SENTINEL, box[1]);
        ok = 0;
    }
    if (box[0] != HARNESS_CANARY || box[2] != HARNESS_CANARY) {
        fprintf(harness_err, "FAIL: %s wrote outside *out (the 8 bytes %s it changed)\n", harness_desc,
                box[0] != HARNESS_CANARY ? "before" : "after");
        ok = 0;
    }
    if (harness_abi_report()) ok = 0;
    if (c->n && memcmp(s, c->src, c->n)) {
        fprintf(harness_err, "FAIL: %s modified s\n", harness_desc);
        ok = 0;
    }
    return ok;
}

/* Appends s[0..n-1] as a C string literal, with octal escapes (always 3 digits, so a following digit can't be
   read as part of the escape) for bytes outside printable ASCII. */
static void harness_fmt_str(char *buf, size_t size, const char *s, size_t n) {
    size_t len = strlen(buf);
    len += (size_t)snprintf(buf + len, size - len, "\"");
    for (size_t i = 0; i < n && len < size; i++) {
        unsigned char ch = (unsigned char)s[i];
        if (ch == '"' || ch == '\\') len += (size_t)snprintf(buf + len, size - len, "\\%c", ch);
        else if (ch < 0x20 || ch > 0x7e) len += (size_t)snprintf(buf + len, size - len, "\\%03o", ch);
        else len += (size_t)snprintf(buf + len, size - len, "%c", ch);
    }
    if (len < size) snprintf(buf + len, size - len, "\"");
}

static void harness_pu_where(const char *s, size_t n, int where) {
    harness_pu_case c = {s, n, where};
    snprintf(harness_desc, sizeof harness_desc, "parse_u64(s = ");
    if (where == HARNESS_NULL) strcat(harness_desc, "NULL");
    else if (where == HARNESS_INACCESSIBLE) strcat(harness_desc, "(pointer into an inaccessible page)");
    else {
        harness_fmt_str(harness_desc, sizeof harness_desc - 120, s, n);
        snprintf(harness_desc + strlen(harness_desc), sizeof harness_desc - strlen(harness_desc), " (%s)",
                 harness_where(where));
    }
    snprintf(harness_desc + strlen(harness_desc), sizeof harness_desc - strlen(harness_desc),
             ", n = %zu, out) with *out = %" PRIu64, n, (uint64_t)HARNESS_OUT_SENTINEL);
    uint64_t value = HARNESS_OUT_SENTINEL;
    if (harness_pu_expected(s, n, &value) == 0)
        snprintf(harness_want, sizeof harness_want, "0 and *out = %" PRIu64, value);
    else
        snprintf(harness_want, sizeof harness_want, "-1 and *out unchanged");
    harness_run(harness_pu_body, &c, 2, NULL);
}

static void harness_pu(const char *s, size_t n) {
    harness_pu_where(s, n, HARNESS_AT_END);
    harness_pu_where(s, n, HARNESS_AT_START);
}

int main(void) {
    harness_init();
    harness_fn = (void *)parse_u64;
    harness_pu_where(NULL, 0, HARNESS_NULL);
    harness_pu_where(NULL, 0, HARNESS_INACCESSIBLE);
    static const char *const valid[] = {
        "0", "9", "0000", "007", "18446744073709551610", "18446744073709551615", "0000018446744073709551615",
    };
    for (size_t i = 0; i < sizeof valid / sizeof *valid; i++) harness_pu(valid[i], strlen(valid[i]));
    static const char *const overflow[] = {
        "18446744073709551616", "18446744073709551620", "36893488147419103230", "99999999999999999999",
        "184467440737095516150",
    };
    for (size_t i = 0; i < sizeof overflow / sizeof *overflow; i++) harness_pu(overflow[i], strlen(overflow[i]));
    static const char *const invalid[] = {"+1", "-1", " 1", "1 ", "123x", "/", ":", "\xb0", "\xff", "9\xb9"};
    for (size_t i = 0; i < sizeof invalid / sizeof *invalid; i++) harness_pu(invalid[i], strlen(invalid[i]));
    harness_pu("12\0" "34", 5);
    harness_pu("7\0", 2);
    const size_t lengths[8] = {1, 7, 8, 15, 16, 17, 20, 25};
    for (int l = 0; l < 8; l++) {
        char digits[32];
        if (lengths[l] < 20) memcpy(digits, "9876543210987654321", lengths[l]);
        else if (lengths[l] == 20) memcpy(digits, "09876543210987654321", 20);
        else memcpy(digits, "0000009876543210987654321", 25);
        harness_pu(digits, lengths[l]);
    }
    return harness_finish();
}

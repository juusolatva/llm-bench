#include <ctype.h>
#include <stddef.h>
#include <string.h>

static void strip(const char **start, const char **end) {
    while (*start < *end && isspace((unsigned char)**start)) (*start)++;
    while (*end > *start && isspace((unsigned char)(*end)[-1])) (*end)--;
}

int parse_kv(const char *line, char *key, size_t keysz, char *val, size_t valsz) {
    const char *p = line;
    while (*p && isspace((unsigned char)*p)) p++;
    if (*p == '\0' || *p == '#') return 0;
    const char *eq = strchr(line, '=');
    if (!eq) return -1;
    const char *ks = line, *ke = eq, *vs = eq + 1, *ve = eq + 1 + strlen(eq + 1);
    strip(&ks, &ke);
    strip(&vs, &ve);
    size_t kn = (size_t)(ke - ks), vn = (size_t)(ve - vs);
    if (kn == 0 || kn + 1 > keysz || vn + 1 > valsz) return -1;
    memcpy(key, ks, kn);
    key[kn] = '\0';
    memcpy(val, vs, vn);
    val[vn] = '\0';
    return 1;
}

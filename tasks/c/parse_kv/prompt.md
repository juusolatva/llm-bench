Write C code for solution.c (no main) implementing:

```c
#include <stddef.h>
int parse_kv(const char *line, char *key, size_t keysz, char *val, size_t valsz);
```

It parses one line of a config file of the form `key = value`:
- Lines that are empty, contain only whitespace, or whose first non-whitespace character is '#' are skipped: return 0.
- The key is the text before the first '=', the value is everything after it. Whitespace (isspace, including a trailing "\n" or "\r\n") at the start and end of both is removed; whitespace inside them is kept. The value may be empty.
- On success, copy key and value as NUL-terminated strings into key and val and return 1.
- Return -1 if there is no '=', the key is empty, or the key or the value (including its NUL) does not fit into keysz or valsz bytes.
- Never write more than keysz bytes to key or valsz bytes to val.

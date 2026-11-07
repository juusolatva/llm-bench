Write C code for solution.c (no main) implementing:

```c
char *join_path(const char *a, const char *b);
```

Return a newly malloc'd string (the caller frees it) that joins two path parts:
- If b starts with '/', it is absolute: return a copy of b.
- If a is empty, return a copy of b. If b is empty, return a copy of a.
- Otherwise remove all trailing '/' characters from a and return a + "/" + b.
- Return NULL if memory allocation fails.

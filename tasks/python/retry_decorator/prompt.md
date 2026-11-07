Write a decorator factory `retry(times, exceptions=(Exception,), delay=1.0, backoff=2.0)` in solution.py.

- The decorated function is called at most `times` times in total.
- If a call raises an exception that is an instance of one of `exceptions`, wait and call it again: wait `delay` seconds before the 2nd call, `delay * backoff` before the 3rd, `delay * backoff**2` before the 4th, and so on. Use `time.sleep` to wait. Do not wait after the last call.
- If every call fails, re-raise the exception from the last call. Exceptions not listed in `exceptions` propagate immediately without retrying.
- Return the result as soon as a call succeeds. Positional and keyword arguments are passed through, and the decorated function keeps its `__name__` and `__doc__`.
- `retry(...)` raises ValueError if `times < 1`.

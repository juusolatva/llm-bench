import functools
import time


def retry(times, exceptions=(Exception,), delay=1.0, backoff=2.0):
    """Decorator factory: call the function up to `times` times, sleeping delay * backoff**k between
    attempts that raise one of `exceptions`; re-raise the last exception if every attempt fails."""
    if times < 1:
        raise ValueError("times must be at least 1")

    def decorator(func):
        """Wrap func with the retry loop."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            """Call func, retrying on the listed exceptions."""
            wait = delay
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    if attempt == times:
                        raise
                time.sleep(wait)
                wait *= backoff
            raise AssertionError("unreachable")
        return wrapper
    return decorator

import functools
import time


def retry(times, exceptions=(Exception,), delay=1.0, backoff=2.0):
    if times < 1:
        raise ValueError("times must be at least 1")

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
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

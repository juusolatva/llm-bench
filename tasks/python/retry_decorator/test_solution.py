import math, time
sleeps = []
time.sleep = lambda s: sleeps.append(s)   # patched before import so any import style sees it
from solution import retry

def close(xs, ys):
    return len(xs) == len(ys) and all(math.isclose(x, y) for x, y in zip(xs, ys))

calls = []
@retry(times=4, exceptions=(ValueError,), delay=0.5, backoff=2)
def flaky(x, y=0):
    "doc here"
    calls.append(1)
    if len(calls) < 3:
        raise ValueError("no")
    return x + y
case = "retry(times=4, exceptions=(ValueError,), delay=0.5, backoff=2) on f(x, y=0) that raises ValueError twice, then returns x + y"
got = flaky(1, y=2)
assert got == 3, f"{case}: f(1, y=2) returned {got!r}, want 3"
assert len(calls) == 3, f"{case}: f was called {len(calls)} times, want 3"
assert close(sleeps, [0.5, 1.0]), f"{case}: time.sleep calls {sleeps}, want [0.5, 1.0]"
assert flaky.__name__ == "flaky" and flaky.__doc__ == "doc here", \
    f"decorated function has __name__ {flaky.__name__!r} and __doc__ {flaky.__doc__!r}, want 'flaky' and 'doc here'"

sleeps.clear(); errs = []
@retry(times=3, exceptions=(KeyError, ValueError), delay=1, backoff=3)
def always():
    e = KeyError(len(errs)); errs.append(e); raise e
case = "retry(times=3, exceptions=(KeyError, ValueError), delay=1, backoff=3) on f() that always raises KeyError"
try:
    got = always()
except KeyError as e:
    assert e is errs[-1], f"{case}: re-raised KeyError({e}), want the exception from the last call, KeyError({len(errs) - 1})"
else:
    raise AssertionError(f"{case}: returned {got!r}, want the last KeyError re-raised")
assert len(errs) == 3, f"{case}: f was called {len(errs)} times, want 3"
assert close(sleeps, [1, 3]), f"{case}: time.sleep calls {sleeps}, want [1, 3]"
sleeps.clear(); errs.clear()
try:
    got = always()
except KeyError:
    pass
else:
    raise AssertionError(f"{case}, calling the decorated f a second time: returned {got!r}, want the last KeyError re-raised")
assert len(errs) == 3 and close(sleeps, [1, 3]), \
    f"{case}, calling the decorated f a second time: {len(errs)} calls with time.sleep calls {sleeps}, want 3 calls and [1, 3] (each call starts again with delay)"

sleeps.clear(); n = []
@retry(times=5, exceptions=(ValueError,), delay=1)
def other():
    n.append(1); raise TypeError("x")
case = "retry(times=5, exceptions=(ValueError,), delay=1) on f() that raises TypeError"
try:
    got = other()
except TypeError:
    pass
else:
    raise AssertionError(f"{case}: returned {got!r}, want TypeError to propagate")
assert len(n) == 1 and sleeps == [], \
    f"{case}: f was called {len(n)} times with time.sleep calls {sleeps}, want 1 call and no sleep (not retried)"

sleeps.clear()
@retry(times=1, delay=1)
def once():
    raise RuntimeError("x")
case = "retry(times=1, delay=1) on f() that raises RuntimeError"
try:
    got = once()
except RuntimeError:
    pass
else:
    raise AssertionError(f"{case}: returned {got!r}, want RuntimeError re-raised")
assert sleeps == [], f"{case}: time.sleep calls {sleeps}, want none (no sleep after the last call)"

sleeps.clear(); d = []
@retry(times=3)
def defaults():
    d.append(1); raise RuntimeError("x")
case = "retry(times=3) (default exceptions, delay and backoff) on f() that raises RuntimeError"
try:
    got = defaults()
except RuntimeError:
    pass
else:
    raise AssertionError(f"{case}: returned {got!r}, want RuntimeError re-raised")
assert len(d) == 3, f"{case}: f was called {len(d)} times, want 3"
assert close(sleeps, [1.0, 2.0]), f"{case}: time.sleep calls {sleeps}, want [1.0, 2.0]"

for bad in (0, -1):
    try:
        retry(times=bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"retry(times={bad}): did not raise, want ValueError")
print("ok")

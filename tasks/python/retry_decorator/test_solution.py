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
assert flaky(1, y=2) == 3 and len(calls) == 3
assert close(sleeps, [0.5, 1.0]), sleeps
assert flaky.__name__ == "flaky" and flaky.__doc__ == "doc here"

sleeps.clear(); errs = []
@retry(times=3, exceptions=(KeyError, ValueError), delay=1, backoff=3)
def always():
    e = KeyError(len(errs)); errs.append(e); raise e
try:
    always()
except KeyError as e:
    assert e is errs[-1], "must re-raise the last exception"
else:
    raise AssertionError("no exception")
assert len(errs) == 3 and close(sleeps, [1, 3]), (len(errs), sleeps)

sleeps.clear(); n = []
@retry(times=5, exceptions=(ValueError,), delay=1)
def other():
    n.append(1); raise TypeError("x")
try:
    other()
except TypeError:
    pass
else:
    raise AssertionError("no exception")
assert len(n) == 1 and sleeps == [], "unlisted exception must not be retried"

sleeps.clear()
@retry(times=1, delay=1)
def once():
    raise RuntimeError("x")
try:
    once()
except RuntimeError:
    pass
assert sleeps == [], "no sleep after the last call"

for bad in (0, -1):
    try:
        retry(times=bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"times={bad}: expected ValueError")
print("ok")

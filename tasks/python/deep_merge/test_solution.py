import copy
from solution import deep_merge


def harness_check(a, b, want):
    a0, b0 = copy.deepcopy(a), copy.deepcopy(b)
    got = deep_merge(a, b)
    assert got == want, f"deep_merge({a0!r}, {b0!r}): got {got!r}, want {want!r}"
    assert a == a0 and b == b0, f"deep_merge({a0!r}, {b0!r}) modified its inputs: a is now {a!r}, b is now {b!r}; want both unchanged"
    return got


a = {"x": 1, "n": {"p": 1, "q": {"r": 1}}, "l": [1], "only_a": {"k": [1, 2]}}
b = {"y": 2, "n": {"q": {"s": 2}, "t": 3}, "l": [2], "only_b": {"k": [3]}}
a0, b0 = copy.deepcopy(a), copy.deepcopy(b)
want = {"x": 1, "y": 2, "n": {"p": 1, "q": {"r": 1, "s": 2}, "t": 3}, "l": [2],
        "only_a": {"k": [1, 2]}, "only_b": {"k": [3]}}
mutations = [
    ('r["n"]["q"]["r"] = 99', lambda r: r["n"]["q"].__setitem__("r", 99)),
    ('r["l"].append(7)', lambda r: r["l"].append(7)),
    ('r["only_a"]["k"].append(9)', lambda r: r["only_a"]["k"].append(9)),
    ('r["only_b"]["k"].append(9)', lambda r: r["only_b"]["k"].append(9)),
    ('r["n"]["new"] = 1', lambda r: r["n"].__setitem__("new", 1)),
    ('r["x"] = 5', lambda r: r.__setitem__("x", 5)),
]
for text, mutate in mutations:
    r = harness_check(a, b, want)
    mutate(r)
    assert a == a0 and b == b0, (f"r = deep_merge({a0!r}, {b0!r}); {text} changed the inputs: a is now {a!r}, "
                                 f"b is now {b!r}; want a and b unchanged ({a0!r} and {b0!r}): the result must not share dicts or lists "
                                 f"with a or b")
    a, b = copy.deepcopy(a0), copy.deepcopy(b0)

only = {"n": {"m": [1]}}
r = harness_check(only, {}, only)
r["n"]["m"].append(2)
assert only == {"n": {"m": [1]}}, (f"r = deep_merge({{'n': {{'m': [1]}}}}, {{}}); r['n']['m'].append(2) changed a to "
                                   f"{only!r}; want a unchanged ({{'n': {{'m': [1]}}}}): the result must not share dicts or lists "
                                   f"with a or b")
for which in ("a", "b"):
    nested = {"l": [[1], {"d": 1}]}
    args = (nested, {}) if which == "a" else ({}, nested)
    shown = ", ".join(repr(x) for x in args)
    r = harness_check(*args, {"l": [[1], {"d": 1}]})
    r["l"][0].append(2)
    r["l"][1]["d"] = 9
    assert nested == {"l": [[1], {"d": 1}]}, (
        f"r = deep_merge({shown}); r['l'][0].append(2); r['l'][1]['d'] = 9 changed {which} to {nested!r}; "
        f"want {which} unchanged ({{'l': [[1], {{'d': 1}}]}}): the result must not share dicts or lists with a or b, including ones nested in lists")
harness_check({"k": 1}, {"k": {"z": 1}}, {"k": {"z": 1}})
harness_check({"k": {"z": 1}}, {"k": None}, {"k": None})
harness_check({"k": {"z": 1}}, {"k": [1]}, {"k": [1]})
harness_check({}, {}, {})
print("harness: all checks passed")

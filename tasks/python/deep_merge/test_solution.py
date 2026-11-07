import copy
from solution import deep_merge

a = {"x": 1, "n": {"p": 1, "q": {"r": 1}}, "l": [1], "only_a": {"k": [1, 2]}}
b = {"y": 2, "n": {"q": {"s": 2}, "t": 3}, "l": [2], "only_b": {"k": [3]}}
a0, b0 = copy.deepcopy(a), copy.deepcopy(b)
r = deep_merge(a, b)
assert r == {"x": 1, "y": 2, "n": {"p": 1, "q": {"r": 1, "s": 2}, "t": 3}, "l": [2],
             "only_a": {"k": [1, 2]}, "only_b": {"k": [3]}}, r
assert a == a0 and b == b0, "inputs modified"
r["n"]["q"]["r"] = 99
r["l"].append(7)
r["only_a"]["k"].append(9)
r["only_b"]["k"].append(9)
r["n"]["new"] = 1
assert a == a0 and b == b0, "result shares objects with inputs"
assert deep_merge({"k": 1}, {"k": {"z": 1}}) == {"k": {"z": 1}}
assert deep_merge({"k": {"z": 1}}, {"k": None}) == {"k": None}
assert deep_merge({}, {}) == {}
print("ok")

from solution import top_customers


def harness_check(rows, want, call="", **kwargs):
    args = ", ".join([repr(rows)] + [f"{k}={v!r}" for k, v in kwargs.items()])
    got = top_customers(list(rows), **kwargs)
    assert got == want, f"{call}top_customers({args}): got {got!r}, want {want!r}"


rows = [("bob", 5), ("alice", 10), ("carol", 5), ("dave", 1)]
want = [("alice", 10), ("bob", 5), ("carol", 5)]
harness_check(rows, want)
harness_check(rows, want, call="second call: ")
harness_check(rows, [("alice", 10), ("bob", 5), ("carol", 5), ("dave", 1)], n=10)
harness_check([("a", 1), ("b", 2), ("a", 2)], [("a", 3), ("b", 2)], n=2)
harness_check([("zed", 2), ("amy", 2), ("kim", 2), ("bo", 3)], [("bo", 3), ("amy", 2), ("kim", 2)])
harness_check([], [])
got = top_customers((r for r in [("y", 1), ("x", 1)]), n=1)
assert got == [("x", 1)], f"top_customers(<generator of [('y', 1), ('x', 1)]>, n=1): got {got!r}, want [('x', 1)]"
print("ok")

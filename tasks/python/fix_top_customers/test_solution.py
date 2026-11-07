from solution import top_customers

rows = [("bob", 5), ("alice", 10), ("carol", 5), ("dave", 1)]
want = [("alice", 10), ("bob", 5), ("carol", 5)]
assert top_customers(rows) == want, top_customers(rows)
assert top_customers(rows) == want, "second call differs (state kept between calls)"
assert top_customers(rows, n=10) == [("alice", 10), ("bob", 5), ("carol", 5), ("dave", 1)]
assert top_customers([("a", 1), ("b", 2), ("a", 2)], n=2) == [("a", 3), ("b", 2)]
assert top_customers([]) == []
assert top_customers((r for r in [("x", 1), ("y", 1)]), n=1) == [("x", 1)]
print("ok")

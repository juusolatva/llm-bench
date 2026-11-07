Write a Python function `deep_merge(a: dict, b: dict) -> dict` in solution.py.

- Return a new dict containing the keys of both a and b.
- When a key exists in both and both values are dicts, merge them recursively. Otherwise the value from b wins (lists and other values are not merged).
- a and b must not be modified, and modifying the result (including nested dicts and lists) must never affect a or b.

This function in solution.py returns wrong results: the order is wrong, ties are not ordered as the docstring says, and calling it twice with the same input gives different results. Fix it and reply with the complete fixed solution.py.

```python
def top_customers(rows, n=3, totals={}):
    """rows: iterable of (customer, amount) tuples.
    Return the n customers with the highest total amount as a list of (customer, total) tuples,
    highest total first; customers with equal totals are ordered by name ascending."""
    for customer, amount in rows:
        totals[customer] = totals.get(customer, 0) + amount
    ranked = sorted(totals.items(), key=lambda kv: kv[1])
    return ranked[:n]
```

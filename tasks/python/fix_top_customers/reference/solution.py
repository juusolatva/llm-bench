def top_customers(rows, n=3):
    """rows: iterable of (customer, amount) tuples.
    Return the n customers with the highest total amount as a list of (customer, total) tuples,
    highest total first; customers with equal totals are ordered by name ascending."""
    totals = {}
    for customer, amount in rows:
        totals[customer] = totals.get(customer, 0) + amount
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:n]

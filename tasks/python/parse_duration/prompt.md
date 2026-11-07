Write a Python function `parse_duration(s: str) -> int` in solution.py that converts a duration string such as "1h30m", "45s" or "2h5m10s" to a number of seconds.

- The units are h, m and s, each preceded by a non-negative integer.
- Each unit appears at most once and in the order h, m, s. Any unit may be omitted, but at least one must be present.
- No spaces or other characters are allowed.
- Raise ValueError for invalid input.

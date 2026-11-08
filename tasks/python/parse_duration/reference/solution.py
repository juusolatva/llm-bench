import re

_DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")


def parse_duration(s: str) -> int:
    """Seconds in a duration like "1h30m" (units h, m, s in that order, each at most once)."""
    match = _DURATION.fullmatch(s)
    if not s or not match or not s.isascii():
        raise ValueError(f"invalid duration: {s!r}")
    h, m, sec = (int(g) if g else 0 for g in match.groups())
    return h * 3600 + m * 60 + sec

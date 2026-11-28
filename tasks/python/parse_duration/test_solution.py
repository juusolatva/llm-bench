from solution import parse_duration

ok = {"1h30m": 5400, "45s": 45, "2h": 7200, "2h5m10s": 7510, "0s": 0, "90m": 5400,
      "1h0m5s": 3605, "100s": 100, "1h1s": 3601, "5m10s": 310}
for s, want in ok.items():
    try:
        got = parse_duration(s)
    except Exception as e:
        raise AssertionError(f"parse_duration({s!r}): raised {e!r}, want {want}") from None
    assert got == want and type(got) is int, f"parse_duration({s!r}): got {got!r}, want {want} (an int)"
for s in ["", "h", "10", "1x", "1m1h", "1s1m", "1s1h", "1h1h", "1m1m", "1s1s", "1H", "1h 30m", "-5s", "1.5h",
          "1hm", "s5", " 45s", "45s ", "45s\n", "+5s", "1_0s"]:
    try:
        got = parse_duration(s)
    except ValueError:
        continue
    except Exception as e:
        raise AssertionError(f"parse_duration({s!r}): raised {e!r}, want ValueError") from None
    raise AssertionError(f"parse_duration({s!r}): returned {got!r}, want ValueError")
print("harness: all checks passed")

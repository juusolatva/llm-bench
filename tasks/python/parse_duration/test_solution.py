from solution import parse_duration

ok = {"1h30m": 5400, "45s": 45, "2h": 7200, "2h5m10s": 7510, "0s": 0, "90m": 5400,
      "1h0m5s": 3605, "100s": 100, "1h1s": 3601}
for s, want in ok.items():
    got = parse_duration(s)
    assert got == want, f"{s!r}: got {got!r}, want {want}"
for s in ["", "h", "10", "1x", "1m1h", "1h1h", "1h 30m", "-5s", "1.5h", "1hm", "s5"]:
    try:
        parse_duration(s)
    except ValueError:
        continue
    raise AssertionError(f"{s!r}: expected ValueError")
print("ok")

Write Go code in `package solution` (standard library only, no main, no tests) with:

```go
func WordFreq(r io.Reader) (map[string]int, error)
```

It counts the words read from r. Words are maximal runs of letters and digits (unicode.IsLetter or unicode.IsDigit), counted case-insensitively and stored in lowercase. Lines can be longer than 64 KiB. If reading from r fails, return the error.

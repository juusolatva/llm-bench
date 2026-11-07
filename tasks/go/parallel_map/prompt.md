Write Go code in `package solution` (standard library only, no main, no tests) with:

```go
func ParallelMap(ctx context.Context, inputs []int, workers int,
	f func(ctx context.Context, x int) (int, error)) ([]int, error)
```

It calls f once for each input, concurrently, and returns the results in the order of inputs:
- At most `workers` calls of f run at the same time (workers >= 1), and when there are enough inputs, `workers` calls do run at the same time.
- If a call of f returns an error, ParallelMap returns the first error returned by any call and a nil slice. It then starts no new calls and cancels the context passed to the calls still running.
- If ctx is canceled, ParallelMap starts no new calls and returns ctx.Err() and a nil slice.
- ParallelMap returns only after every call of f it started has returned.
- For empty inputs it returns a slice of length 0 and a nil error.

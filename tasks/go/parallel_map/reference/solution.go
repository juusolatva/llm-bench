package solution

import (
	"context"
	"sync"
)

// ParallelMap calls f for every input with at most `workers` calls running at once and returns the
// results in input order, or the first error returned by f (ctx.Err() if ctx was canceled).
func ParallelMap(ctx context.Context, inputs []int, workers int,
	f func(ctx context.Context, x int) (int, error)) ([]int, error) {
	parent := ctx
	ctx, cancel := context.WithCancel(parent)
	defer cancel()

	results := make([]int, len(inputs))
	var (
		mu       sync.Mutex
		firstErr error
		wg       sync.WaitGroup
	)
	sem := make(chan struct{}, workers)
	for i, x := range inputs {
		select {
		case <-ctx.Done():
		case sem <- struct{}{}:
		}
		if ctx.Err() != nil {
			break
		}
		wg.Add(1)
		go func(i, x int) {
			defer wg.Done()
			defer func() { <-sem }()
			if ctx.Err() != nil { // canceled while this goroutine was being scheduled
				return
			}
			v, err := f(ctx, x)
			if err != nil {
				mu.Lock()
				if firstErr == nil {
					firstErr = err
					cancel()
				}
				mu.Unlock()
				return
			}
			results[i] = v
		}(i, x)
	}
	wg.Wait()
	if err := parent.Err(); err != nil {
		return nil, err
	}
	if firstErr != nil {
		return nil, firstErr
	}
	return results, nil
}

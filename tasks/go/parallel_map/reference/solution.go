package solution

import (
	"context"
	"sync"
)

// ParallelMap calls f for every input with at most `workers` calls running at once and returns the
// results in input order, or the first error.
func ParallelMap(ctx context.Context, inputs []int, workers int,
	f func(ctx context.Context, x int) (int, error)) ([]int, error) {
	ctx, cancel := context.WithCancel(ctx)
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
	if firstErr != nil {
		return nil, firstErr
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return results, nil
}

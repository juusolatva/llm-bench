package solution

import "sync"

// CountLengths returns how many strings of each length are in words, computed concurrently.
func CountLengths(words []string) map[int]int {
	counts := map[int]int{}
	var mu sync.Mutex
	var wg sync.WaitGroup
	for _, w := range words {
		wg.Add(1)
		go func(w string) {
			defer wg.Done()
			mu.Lock()
			counts[len(w)]++
			mu.Unlock()
		}(w)
	}
	wg.Wait()
	return counts
}

This Go function sometimes crashes and sometimes returns wrong counts. Fix it (keep it concurrent) and reply with the complete fixed file.

```go
package solution

import "sync"

// CountLengths returns how many strings of each length are in words, computed concurrently.
func CountLengths(words []string) map[int]int {
	counts := map[int]int{}
	var wg sync.WaitGroup
	for _, w := range words {
		go func() {
			wg.Add(1)
			counts[len(w)]++
			wg.Done()
		}()
	}
	wg.Wait()
	return counts
}
```

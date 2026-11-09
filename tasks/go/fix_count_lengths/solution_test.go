package solution

import (
	"fmt"
	"os"
	"reflect"
	"strings"
	"testing"
)

// TestMain prints the harness's final line only after every test passed. The benchmark requires it, so a
// solution that ends the process early (e.g. os.Exit(0) in an init function) fails.
func TestMain(m *testing.M) {
	code := m.Run()
	if code == 0 {
		fmt.Println("harness: all checks passed")
	}
	os.Exit(code)
}

func TestCountLengths(t *testing.T) {
	words := make([]string, 5000)
	want := map[int]int{}
	for i := range words {
		words[i] = strings.Repeat("x", i%17)
		want[i%17]++
	}
	for round := 0; round < 20; round++ {
		if got := CountLengths(words); !reflect.DeepEqual(got, want) {
			t.Fatalf("round %d: CountLengths(5000 words, word i is strings.Repeat(\"x\", i%%17)): got %v, want %v",
				round, got, want)
		}
	}
	if got := CountLengths(nil); len(got) != 0 {
		t.Fatalf("CountLengths(nil): got %v, want an empty map", got)
	}
}
